// ft-screens: a minimal Wayland compositor that hosts the nested KWin and shows each of
// its screens as its own SteamVR panel. It replaces gamescope for Frametop:
//   - KWin (nested Wayland backend) opens one window per screen. We send each window its
//     size (xdg_toplevel configure), and KWin resizes that screen to match, so every
//     screen has its own resolution and shape (ultrawide, portrait, 4K...). gamescope
//     never sized its windows and drew them all into one canvas of at most 1920x1080.
//   - KWin renders into DMA-BUFs and hands them to us (linux-dmabuf). We draw nothing:
//     each buffer goes to SteamVR as the panel's texture (vr.cpp, ImportDmabuf).
//   - Pointer input from the panels (controller lasers, the 3D mouse) goes to KWin through
//     our seat, as if we were a normal desktop. KWin's nested backend adds our surface
//     coordinates to its output's logical position without undoing its own scale, and its
//     buffers are in pixels, so a panel position in pixels is divided by the screen's KWin
//     scale first ("scale <screen> <s>", from ft-layout).
//
// Usage: ft-screens [--socket NAME] [--control NAME] [--no-vr] [--beside] [--screen WxH@METRES]...
//                   [--spares N] [--rates F,V,H] [-- COMMAND ARGS...]
//   --socket    Wayland socket name in $XDG_RUNTIME_DIR (default ft-screens-0)
//   --control   the control socket's abstract name (default ft_screens)
//   --no-vr     run without SteamVR, for tests next to the running desktop: no panels, no
//               input, and nothing sent to the input relay. Commands still work, and
//               "toplevels" shows what KWin opened.
//   --beside    with SteamVR, next to the running desktop, for remote screens (remote.c):
//               nothing goes to the input relay, ft-floatd or ft-layout. Use other --socket
//               and --control names, and no COMMAND.
//   --screen    one per screen, in KWin's order (default: 3440x1440@2.4)
//   --spares    KWin's outputs after the screens: spares for floating windows (ft-floatd
//               turns them on and sizes them; see docs/floating-windows.md)
//   --rates     frame rates in Hz for screens you look at, the rest you see, and hidden ones
//               (0: every display frame; default 0,15,1; see frame_interval)
//   COMMAND     run with WAYLAND_DISPLAY set to our socket (e.g. the Frametop session)
// Runs in the dev container (wlroots 0.20); KWin connects from the host.
#define _GNU_SOURCE
#include <drm_fourcc.h>
#include <linux/input-event-codes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <sys/socket.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/timerfd.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <wayland-server-core.h>
#include <xkbcommon/xkbcommon.h>

#define WLR_USE_UNSTABLE
#include <wlr/interfaces/wlr_keyboard.h>
#include <wlr/render/dmabuf.h>
#include <wlr/render/drm_format_set.h>
#include <wlr/types/wlr_buffer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_keyboard.h>
#include <wlr/types/wlr_linux_dmabuf_v1.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_shm.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_xdg_decoration_v1.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/log.h>

#include "vr.h"
#include "controller-click.h"
#include "chord-click.h"
#include "output-bind.h"
#include "keyboard-focus.h"
#include "pointer-map.h"
#include "remote.h"
#include "relay-buttons.h"

#define MAX_SCREENS 24  // screens and spare outputs
// A screen counts as playing a video while its last VIDEO_COMMITS commits each redrew at
// least VIDEO_AREA percent of it, at VIDEO_HZ or more; for VIDEO_HOLD ms after that stops.
#define VIDEO_COMMITS 8
#define VIDEO_AREA 6
#define VIDEO_HZ 10
#define VIDEO_HOLD 1500

struct config {
    int width, height;
    double metres;
};

struct server;

// One KWin window = one screen.
struct screen {
    struct server *server;
    int index;
    struct wlr_xdg_toplevel *toplevel;
    struct wlr_buffer *held;      // on the panel now; unlocked when the next one arrives
    bool frame_pending;           // a commit waits for its frame callback
    unsigned commits;             // buffers committed, and the last one's size ("toplevels")
    int buffer_width, buffer_height;
    struct wlr_xdg_toplevel_decoration_v1 *decoration;  // answered on the first commit
    struct wl_listener commit, destroy, decoration_destroy, set_title;
    char monitor[FT_OUTPUT_NAME_MAX];  // Aquamarine's WAYLAND-N, once the title arrives
    bool need_size;                     // initial commit happened before the slot was known
    bool panel;                         // ft_vr_screen_create has a panel for this slot
    // Its frame rate (see tick): when its last frame callback went (ms), and what its recent
    // commits looked like, to tell a video playing on it.
    uint32_t frame_sent;
    uint32_t commit_ms[VIDEO_COMMITS];
    unsigned commit_at;
    unsigned big;          // a bit per recent commit: it redrew at least VIDEO_AREA percent
    uint32_t video_until;  // counts as a video until then (ms)
};

// Per client buffer: forget its import when it goes away.
struct tracked_buffer {
    struct wlr_buffer *buffer;
    struct wl_listener destroy;
    struct wl_list link;
};

struct server {
    struct wl_display *display;
    struct wl_event_loop *loop;
    struct wlr_seat *seat;
    struct wlr_keyboard keyboard;
    struct wlr_xdg_shell *xdg_shell;
    struct wlr_xdg_decoration_manager_v1 *decoration;
    struct wl_listener new_toplevel, new_decoration;
    struct screen *screens[MAX_SCREENS];
    struct screen *pending[MAX_SCREENS];  // Hyprland toplevels waiting for a claim
    struct ft_output_table claims;
    bool output_names;  // FT_OUTPUT_NAMES=1: slot comes from a claim, not arrival order
    struct config config[MAX_SCREENS];
    double scale[MAX_SCREENS];  // KWin's scale for each screen (panel pixels per logical unit)
    int n_config, n_screens;  // n_config: the screens; the outputs after them are spares
    int spares;
    struct wl_list buffers;  // tracked_buffer
    struct wl_event_source *tick;
    int tick_fd;  // timerfd, at absolute times in step with the display's vsync (see schedule)
    int64_t period_ns, base_ns, synced_ns;  // the display's frame time, a tick time, last sync
    double phase_ms;                        // ticks come this long after a vsync
    // Frame rates in Hz for each attention level (0: every display frame), and a remote
    // viewer's lease: until then (ms) every screen gets full rate ("watch").
    int rate[3];
    uint32_t watch_until;
    uint32_t typed_ms;  // the last key sent to the desktop: its screen counts as focused
    struct screen *pointer_focus;
    struct ft_relay_buttons relay_buttons;  // the input relay's mouse buttons held on the seat
    struct ft_controller_click controller_click;
    struct ft_chord_guard chord;  // trigger+R1: swallow the click, including a late release
    pid_t child;
    // Where typing goes: the screens after a click on one, Steam after a click on another
    // panel. The input relay grabs the keyboards while it's the screens (see keys_update).
    bool keys_clicked;    // the last click was on a screen
    bool keys_desktop;    // ...and the screens are showing: typing goes to the desktop
    int key_remote;       // the last click was on this remote screen (index): typing goes to it; -1 not
    int relay_fd;         // unbound, so the relay can't reply into our control socket
    uint32_t relay_sent;  // when the relay last heard from us (ms)
    unsigned ticks;
    // Our keyboard ("vrkeyboard" commands from the input relay; see keyboard_command).
    int kb_screen;         // the screen it's open for, -1 closed
    bool kb_auto;          // opened for a focused text field (not by a button)
    unsigned kb_close_at;  // ticks: close it then (a text field lost focus), 0 not
    bool vr;               // connected to SteamVR (not --no-vr)
    bool beside;           // a second instance next to the desktop (--beside): remote screens only
};

static uint32_t now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

// ---------------------------------------------------------------- buffers

static void buffer_destroyed(struct wl_listener *l, void *data) {
    struct tracked_buffer *t = wl_container_of(l, t, destroy);
    ft_vr_forget(t->buffer);
    wl_list_remove(&t->destroy.link);
    wl_list_remove(&t->link);
    free(t);
}

static void track_buffer(struct server *s, struct wlr_buffer *buffer) {
    struct tracked_buffer *t;
    wl_list_for_each(t, &s->buffers, link) if (t->buffer == buffer) return;
    t = calloc(1, sizeof *t);
    t->buffer = buffer;
    t->destroy.notify = buffer_destroyed;
    wl_signal_add(&buffer->events.destroy, &t->destroy);
    wl_list_insert(&s->buffers, &t->link);
}

// ---------------------------------------------------------------- screens

static bool relay_can_press(struct server *s);
static void release_relay_buttons(struct server *s, const char *why);

static void apply_screen_size(struct screen *sc) {
    const struct config *c = &sc->server->config[sc->index];
    wlr_xdg_toplevel_set_size(sc->toplevel, c->width, c->height);
    wlr_xdg_toplevel_set_activated(sc->toplevel, true);
    if (sc->decoration)
        wlr_xdg_toplevel_decoration_v1_set_mode(sc->decoration, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
}

static bool park_screen(struct server *s, struct screen *sc) {
    for (int i = 0; i < MAX_SCREENS; ++i) {
        if (!s->pending[i]) {
            s->pending[i] = sc;
            return true;
        }
    }
    return false;
}

static void unpark_screen(struct server *s, struct screen *sc) {
    for (int i = 0; i < MAX_SCREENS; ++i)
        if (s->pending[i] == sc) s->pending[i] = NULL;
}

static void unbind_screen(struct screen *sc) {
    struct server *s = sc->server;
    if (sc->index < 0) return;
    if (s->pointer_focus == sc) {
        release_relay_buttons(s, "its screen moved");
        s->pointer_focus = NULL;
    }
    if (sc->panel) ft_vr_screen_destroy(sc->index);
    sc->panel = false;
    if (s->screens[sc->index] == sc) s->screens[sc->index] = NULL;
    sc->index = -1;
    (void)park_screen(s, sc);
}

// Slot is 1-based. A claim for a slot that already shows another monitor
// parks that monitor; the named one takes the slot.
static void bind_screen(struct screen *sc, int slot) {
    struct server *s = sc->server;
    const int index = slot - 1;
    if (index < 0 || index >= s->n_config || index >= MAX_SCREENS) return;
    if (sc->index == index && s->screens[index] == sc) return;
    struct screen *other = s->screens[index];
    if (other && other != sc) unbind_screen(other);
    if (sc->index >= 0) unbind_screen(sc);
    unpark_screen(s, sc);
    sc->index = index;
    s->screens[index] = sc;
    if (!sc->panel) {
        const struct config *c = &s->config[index];
        wlr_log(WLR_INFO, "screen %d: Hyprland output %s, %dx%d, %.2f m wide",
                slot, sc->monitor[0] ? sc->monitor : "?", c->width, c->height, c->metres);
        ft_vr_screen_create(index, c->metres, s->n_config);
        sc->panel = true;
    }
    if (sc->need_size) apply_screen_size(sc);
}

static void consider_screen(struct screen *sc) {
    if (!sc->monitor[0]) return;
    const int slot = ft_output_screen(&sc->server->claims, sc->monitor);
    if (slot > 0) bind_screen(sc, slot);
}

static void consider_named(struct server *s, const char *monitor) {
    for (int i = 0; i < MAX_SCREENS; ++i) {
        struct screen *sc = s->pending[i];
        if (sc && strcmp(sc->monitor, monitor) == 0) consider_screen(sc);
    }
    for (int i = 0; i < MAX_SCREENS; ++i) {
        struct screen *sc = s->screens[i];
        if (sc && strcmp(sc->monitor, monitor) == 0) consider_screen(sc);
    }
}

static struct screen *screen_by_toplevel(struct server *s, struct wlr_xdg_toplevel *toplevel) {
    for (int i = 0; i < MAX_SCREENS; ++i) {
        if (s->screens[i] && s->screens[i]->toplevel == toplevel) return s->screens[i];
        if (s->pending[i] && s->pending[i]->toplevel == toplevel) return s->pending[i];
    }
    return NULL;
}

// A video (or anything moving over a large area) on a screen you don't look at keeps the
// full frame rate (see frame_interval): its commits keep redrawing much of it, and keep
// coming as fast as its rate lets them. A cursor blinking or a spinner turning redraws a
// small part, and a page changing now and then doesn't keep coming.
static void note_damage(struct screen *sc, struct wlr_surface *surface, struct wlr_buffer *buffer) {
    int n = 0;
    const pixman_box32_t *r = pixman_region32_rectangles(&surface->buffer_damage, &n);
    int64_t area = 0;
    for (int i = 0; i < n; ++i) area += (int64_t)(r[i].x2 - r[i].x1) * (r[i].y2 - r[i].y1);
    const bool big = area * 100 >= (int64_t)buffer->width * buffer->height * VIDEO_AREA;
    const unsigned all = (1u << VIDEO_COMMITS) - 1;
    sc->big = ((sc->big << 1) | big) & all;
    const uint32_t t = now_ms();
    const uint32_t oldest = sc->commit_ms[sc->commit_at];  // the commit VIDEO_COMMITS ago
    sc->commit_ms[sc->commit_at] = t;
    sc->commit_at = (sc->commit_at + 1) % VIDEO_COMMITS;
    if (sc->big == all && t - oldest <= VIDEO_COMMITS * 1000 / VIDEO_HZ) sc->video_until = t + VIDEO_HOLD;
}

static void screen_commit(struct wl_listener *l, void *data) {
    struct screen *sc = wl_container_of(l, sc, commit);
    struct wlr_xdg_surface *xdg = sc->toplevel->base;
    if (xdg->initial_commit) {
        // A Hyprland output may commit before its monitor name is claimed.
        // The size goes out once the slot is known. KWin is already in a slot.
        if (sc->server->output_names) {
            // The slot may still be unknown. Hyprland does not finish creating
            // the output until this toplevel is configured, and the claim waits
            // for that output, so a parked window still gets a size here.
            sc->need_size = true;
            if (sc->index >= 0) {
                apply_screen_size(sc);
            } else {
                const struct config *c = &sc->server->config[0];
                int w = 1920, h = 1080;
                if (sc->server->n_config > 0 && c->width >= 320 && c->height >= 200) {
                    w = c->width;
                    h = c->height;
                }
                wlr_xdg_toplevel_set_size(sc->toplevel, w, h);
                wlr_xdg_toplevel_set_activated(sc->toplevel, true);
                if (sc->decoration)
                    wlr_xdg_toplevel_decoration_v1_set_mode(sc->decoration, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
            }
            return;
        }
        // First commit: tell KWin the size of this screen.
        const struct config spare = {640, 480, 0.5};  // until ft-floatd sizes it
        const struct config *c = sc->index < sc->server->n_config ? &sc->server->config[sc->index] : &spare;
        wlr_xdg_toplevel_set_size(sc->toplevel, c->width, c->height);
        wlr_xdg_toplevel_set_activated(sc->toplevel, true);
        if (sc->decoration)
            wlr_xdg_toplevel_decoration_v1_set_mode(sc->decoration, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
        return;
    }
    if (sc->index < 0) return;
    struct wlr_buffer *buffer = xdg->surface->current.buffer;
    static int logged;
    if (logged < 6) {
        ++logged;
        wlr_log(WLR_INFO, "screen %d: commit, buffer %p (%dx%d), mapped %d", sc->index + 1, (void *)buffer,
                buffer ? buffer->width : 0, buffer ? buffer->height : 0, xdg->surface->mapped);
    }
    if (!buffer) return;
    sc->frame_pending = true;
    ++sc->commits;
    note_damage(sc, xdg->surface, buffer);
    sc->buffer_width = buffer->width, sc->buffer_height = buffer->height;
    if (buffer == sc->held) return;
    struct wlr_dmabuf_attributes a;
    if (!wlr_buffer_get_dmabuf(buffer, &a)) {
        static bool warned;
        if (!warned) wlr_log(WLR_ERROR, "screen %d: not a DMA-BUF (shm?); skipped", sc->index + 1);
        warned = true;
        return;
    }
    struct ft_dmabuf b = {.width = a.width, .height = a.height, .format = a.format, .modifier = a.modifier,
                          .n_planes = a.n_planes};
    for (int i = 0; i < a.n_planes && i < 4; ++i) {
        b.offset[i] = a.offset[i];
        b.stride[i] = a.stride[i];
        b.fd[i] = a.fd[i];
    }
    track_buffer(sc->server, buffer);
    if (!ft_vr_screen_present(sc->index, buffer, &b)) return;
    // Keep this buffer until the next frame replaces it, so SteamVR never samples a
    // buffer KWin is drawing into; then let KWin have the previous one back.
    wlr_buffer_lock(buffer);
    if (sc->held) wlr_buffer_unlock(sc->held);
    sc->held = buffer;
}

static void screen_destroy(struct wl_listener *l, void *data) {
    struct screen *sc = wl_container_of(l, sc, destroy);
    struct server *s = sc->server;
    wlr_log(WLR_INFO, "screen %d closed", sc->index >= 0 ? sc->index + 1 : 0);
    if (sc->held) wlr_buffer_unlock(sc->held);
    if (sc->index >= 0 && (sc->panel || !s->output_names)) ft_vr_screen_destroy(sc->index);
    if (s->pointer_focus == sc) {
        release_relay_buttons(s, "its screen closed");
        s->pointer_focus = NULL;
    }
    if (sc->decoration) wl_list_remove(&sc->decoration_destroy.link);
    if (sc->index >= 0 && s->screens[sc->index] == sc) s->screens[sc->index] = NULL;
    unpark_screen(s, sc);
    if (sc->monitor[0]) ft_output_release_monitor(&s->claims, sc->monitor);
    wl_list_remove(&sc->commit.link);
    wl_list_remove(&sc->destroy.link);
    wl_list_remove(&sc->set_title.link);
    free(sc);
}

// KWin titles each window "KDE Wayland Compositor <output name>", with "- Output disabled"
// after it while that output is off.
static void screen_title(struct wl_listener *l, void *data) {
    struct screen *sc = wl_container_of(l, sc, set_title);
    const char *title = sc->toplevel->title ? sc->toplevel->title : "";
    if (sc->server->output_names) {
        char name[FT_OUTPUT_NAME_MAX];
        if (ft_output_monitor_name(title, name, sizeof name)) {
            snprintf(sc->monitor, sizeof sc->monitor, "%s", name);
            consider_screen(sc);
        }
        wlr_log(WLR_INFO, "screen %d: \"%s\"", sc->index >= 0 ? sc->index + 1 : 0, title);
        return;
    }
    wlr_log(WLR_INFO, "screen %d: \"%s\"", sc->index + 1, title);
    if (sc->index >= sc->server->n_config) ft_vr_float_output(sc->index, !strstr(title, "Output disabled"));
}

static void new_toplevel(struct wl_listener *l, void *data) {
    struct server *s = wl_container_of(l, s, new_toplevel);
    struct wlr_xdg_toplevel *toplevel = data;
    int index = 0;
    while (index < MAX_SCREENS && s->screens[index]) ++index;
    if (index == MAX_SCREENS) {
        wlr_log(WLR_ERROR, "more than %d screens; ignoring one", MAX_SCREENS);
        return;
    }
    struct screen *sc = calloc(1, sizeof *sc);
    sc->server = s;
    sc->toplevel = toplevel;
    if (s->output_names) {
        // Do not take the first free slot. The title names the monitor, and
        // a claim names the slot. Until both exist this toplevel has no panel.
        sc->index = -1;
        if (!park_screen(s, sc)) {
            wlr_log(WLR_ERROR, "more than %d Hyprland outputs waiting; ignoring one", MAX_SCREENS);
            free(sc);
            return;
        }
        char name[FT_OUTPUT_NAME_MAX];
        if (toplevel->title && ft_output_monitor_name(toplevel->title, name, sizeof name)) {
            snprintf(sc->monitor, sizeof sc->monitor, "%s", name);
            consider_screen(sc);
        }
        sc->commit.notify = screen_commit;
        wl_signal_add(&toplevel->base->surface->events.commit, &sc->commit);
        sc->destroy.notify = screen_destroy;
        wl_signal_add(&toplevel->events.destroy, &sc->destroy);
        sc->set_title.notify = screen_title;
        wl_signal_add(&toplevel->events.set_title, &sc->set_title);
        return;
    }
    sc->index = index;
    s->screens[index] = sc;
    if (index >= s->n_config) {
        wlr_log(WLR_INFO, "screen %d: KWin window, a spare output (floating window %d)", index + 1,
                index - s->n_config + 1);
        ft_vr_float_create(index, index - s->n_config + 1);
    } else {
        const struct config *c = &s->config[index];
        wlr_log(WLR_INFO, "screen %d: KWin window, %dx%d, %.2f m wide", index + 1, c->width, c->height, c->metres);
        ft_vr_screen_create(index, c->metres, s->n_config);
    }
    sc->commit.notify = screen_commit;
    wl_signal_add(&toplevel->base->surface->events.commit, &sc->commit);
    sc->destroy.notify = screen_destroy;
    wl_signal_add(&toplevel->events.destroy, &sc->destroy);
    sc->set_title.notify = screen_title;
    wl_signal_add(&toplevel->events.set_title, &sc->set_title);
}

// KWin asks for server-side decorations for its screens; we draw none. It asks before its
// first commit, when a configure isn't allowed yet, so the answer waits for that commit.
static void decoration_destroyed(struct wl_listener *l, void *data) {
    struct screen *sc = wl_container_of(l, sc, decoration_destroy);
    wl_list_remove(&sc->decoration_destroy.link);
    sc->decoration = NULL;
}

static void new_decoration(struct wl_listener *l, void *data) {
    struct server *s = wl_container_of(l, s, new_decoration);
    struct wlr_xdg_toplevel_decoration_v1 *d = data;
    struct screen *sc = screen_by_toplevel(s, d->toplevel);
    if (!sc) return;
    sc->decoration = d;
    sc->decoration_destroy.notify = decoration_destroyed;
    wl_signal_add(&d->events.destroy, &sc->decoration_destroy);
    if (d->toplevel->base->initialized)
        wlr_xdg_toplevel_decoration_v1_set_mode(d, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
}

// ---------------------------------------------------------------- input from the panels

static void panel_key(struct server *s, uint32_t code, bool pressed);
static int focused_screen(struct server *s);

// Typing goes to remote screen `index` (or to the desktop: -1). The one it leaves lets go of
// the keys it held.
static void set_key_remote(struct server *s, int index) {
    if (s->key_remote >= 0 && s->key_remote != index) ft_remote_blur(s->key_remote);
    s->key_remote = index;
}

static void relay_say(struct server *s, const char *msg) {
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    const char name[] = "frametop_relay";
    memcpy(addr.sun_path + 1, name, sizeof name - 1);
    sendto(s->relay_fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&addr,
           offsetof(struct sockaddr_un, sun_path) + 1 + sizeof name - 1);
}

static void note_pointer_slot(struct server *s);

static void handle_vr_event(const struct ft_event *e, void *data) {
    struct server *s = data;
    if (e->type == FT_QUIT) {
        wl_display_terminate(s->display);
        return;
    }
    if (e->type == FT_KEY) {
        panel_key(s, e->key, e->pressed);
        return;
    }
    // Trigger + R3. SteamVR still delivers R3 as a right click, attributed to the
    // hand controller or to the ft_pointer virtual controller. The relay arms the
    // guard while the trigger is down. A press that was swallowed stays swallowed
    // if the trigger is released first, so that release is not a right click.
    // A mouse right click is neither source, so it is delivered while the chord is armed.
    // R1 stays a normal left click.
    if (e->type == FT_BUTTON && e->button == BTN_RIGHT) {
        bool candidate = ft_chord_is_controller_click(e->controller, e->virtual_pointer, true);
        if (candidate || s->chord.armed || s->chord.held) {
            wlr_log(WLR_INFO, "chord click: hand=%d virtual_pointer=%d armed=%d held=%d pressed=%d",
                    e->controller, e->virtual_pointer, s->chord.armed, s->chord.held, e->pressed);
        }
        if (candidate) {
            bool notify = false;
            if (ft_chord_guard_button(&s->chord, e->pressed, &notify) == FT_CHORD_SWALLOW) {
                if (notify) relay_say(s, e->pressed ? "chord-fired" : "chord-released");
                return;
            }
        }
    }
    if (e->type == FT_KEYBOARD_CLOSED) {
        if (s->kb_screen >= 0) wlr_log(WLR_INFO, "keyboard closed");
        s->kb_screen = -1;
        s->kb_close_at = 0;
        return;
    }
    if (ft_remote_is(e->screen)) {
        // Another machine's display: its stream takes the input, and a click or a spin to it
        // takes the typing there too.
        if ((e->type == FT_BUTTON && e->pressed) || e->type == FT_FRONT) {
            set_key_remote(s, e->screen);
            s->keys_clicked = true;
        }
        ft_remote_event(e);
        return;
    }
    if (e->screen < 0 || e->screen >= MAX_SCREENS || !s->screens[e->screen]) return;
    struct ft_event filtered = *e;
    if (e->screen < s->n_config &&
        !ft_controller_click_filter(&s->controller_click, &filtered, s->scale[e->screen])) return;
    e = &filtered;
    if (e->screen < 0 || e->screen >= MAX_SCREENS || !s->screens[e->screen]) return;
    struct screen *sc = s->screens[e->screen];
    struct wlr_surface *surface = sc->toplevel->base->surface;
    if (e->type == FT_FRONT) {
        // A spin brought this panel to the front: typing goes to it, as after a click there,
        // and ft-floatd makes its window (or the top one on a screen) KWin's active window.
        wlr_seat_keyboard_notify_enter(s->seat, surface, NULL, 0, NULL);
        s->keys_clicked = true;
        set_key_remote(s, -1);
        if (s->beside) return;
        char msg[32];
        snprintf(msg, sizeof msg, "front %d", e->screen + 1);
        struct sockaddr_un addr = {.sun_family = AF_UNIX};
        const char name[] = "frametop_float";
        memcpy(addr.sun_path + 1, name, sizeof name - 1);
        sendto(s->relay_fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&addr,
               offsetof(struct sockaddr_un, sun_path) + 1 + sizeof name - 1);
        return;
    }
    const uint32_t t = now_ms();
    double x = e->x / s->scale[e->screen], y = e->y / s->scale[e->screen];  // KWin's units
    switch (e->type) {
        case FT_MOTION:
        case FT_BUTTON:
            if (s->pointer_focus != sc) {
                // KWin's nested backend ignores the position in wl_pointer.enter, and wlroots
                // drops a motion to the position it entered at, so KWin would keep its old
                // pointer until the next move: a press right after crossing onto another
                // screen landed where the pointer had been. Entering one unit off makes the
                // motion below go through.
                wlr_seat_pointer_notify_enter(s->seat, surface, x + 1, y);
                s->pointer_focus = sc;
            }
            // The laser hits one panel. A pointer that leaves that panel's
            // pixel row continues on the neighbour, which is the Hyprland
            // monitor placed beside it. One hop, so the edges cannot chase.
            if (s->output_names && e->type == FT_MOTION && sc->index >= 0 && sc->index < s->n_config &&
                s->scale[sc->index] > 0) {
                const double logical_w = s->config[sc->index].width / s->scale[sc->index];
                int hop = 0;
                if (x < 0) hop = -1;
                else if (logical_w > 0 && x >= logical_w) hop = 1;
                if (hop) {
                    int j = sc->index + hop;
                    while (j >= 0 && j < s->n_config && !s->screens[j]) j += hop;
                    if (j >= 0 && j < s->n_config && s->screens[j] && s->screens[j] != sc) {
                        sc = s->screens[j];
                        surface = sc->toplevel->base->surface;
                        const double next_w = s->config[sc->index].width / s->scale[sc->index];
                        x = hop < 0 ? (next_w > 1 ? next_w - 1 : 0) : 0;
                        y = e->y / s->scale[sc->index];
                        s->pointer_focus = NULL;
                    }
                }
            }
            // Hyprland treats the absolute pointer as a fraction of the whole
            // monitor row. Send the surface x that lands on this screen.
            if (s->output_names && sc->index >= 0 && sc->index < s->n_config) {
                double widths[24], heights[24];
                int present[24];
                int n = s->n_config < 24 ? s->n_config : 24;
                for (int i = 0; i < n; ++i) {
                    double scale = s->scale[i] > 0 ? s->scale[i] : 1;
                    widths[i] = s->config[i].width / scale;
                    heights[i] = s->config[i].height / scale;
                    present[i] = s->screens[i] != NULL;
                }
                ft_pointer_for_row(n, widths, heights, present, sc->index, &x, &y);
            }
            if (s->pointer_focus != sc) {
                wlr_seat_pointer_notify_enter(s->seat, surface, x + 1, y);
                s->pointer_focus = sc;
            }
            wlr_seat_pointer_notify_motion(s->seat, t, x, y);
            // On Hyprland, the panel most recently pointed at remains the
            // keyboard target after the laser leaves the desktop. A click on
            // another SteamVR overlay still clears keys_clicked below.
            if (s->output_names) {
                s->keys_clicked = true;
                set_key_remote(s, -1);
                if (s->seat->keyboard_state.focused_surface != surface)
                    wlr_seat_keyboard_notify_enter(s->seat, surface, NULL, 0, NULL);
            }
            if (e->type == FT_BUTTON) {
                wlr_seat_pointer_notify_button(s->seat, t, e->button,
                                               e->pressed ? WL_POINTER_BUTTON_STATE_PRESSED
                                                          : WL_POINTER_BUTTON_STATE_RELEASED);
                if (e->pressed) {
                    wlr_seat_keyboard_notify_enter(s->seat, surface, NULL, 0, NULL);
                    s->keys_clicked = true;
                    set_key_remote(s, -1);
                }
            }
            break;
        case FT_SCROLL:
            if (s->pointer_focus != sc) break;
            if (sc->index >= s->n_config && e->dy != 0 &&
                (wlr_keyboard_get_modifiers(&s->keyboard) & WLR_MODIFIER_LOGO)) {
                // Meta+scroll on a floating window: its scale, bigger or smaller (ft-floatd).
                char msg[48];
                snprintf(msg, sizeof msg, "scale %d %d", sc->index + 1, e->dy < 0 ? 1 : -1);
                struct sockaddr_un addr = {.sun_family = AF_UNIX};
                const char name[] = "frametop_float";
                memcpy(addr.sun_path + 1, name, sizeof name - 1);
                sendto(s->relay_fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&addr,
                       offsetof(struct sockaddr_un, sun_path) + 1 + sizeof name - 1);
                break;
            }
            if (e->dy != 0)
                wlr_seat_pointer_notify_axis(s->seat, t, WL_POINTER_AXIS_VERTICAL_SCROLL, e->dy * 15,
                                             (int32_t)(e->dy * 120), WL_POINTER_AXIS_SOURCE_WHEEL,
                                             WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL);
            if (e->dx != 0)
                wlr_seat_pointer_notify_axis(s->seat, t, WL_POINTER_AXIS_HORIZONTAL_SCROLL, e->dx * 15,
                                             (int32_t)(e->dx * 120), WL_POINTER_AXIS_SOURCE_WHEEL,
                                             WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL);
            break;
        case FT_LEAVE:
            if (s->pointer_focus == sc) {
                release_relay_buttons(s, "the pointer left the screens");
                wlr_seat_pointer_notify_clear_focus(s->seat);
                s->pointer_focus = NULL;
            }
            break;
        default:
            break;
    }
    note_pointer_slot(s);
    wlr_seat_pointer_notify_frame(s->seat);
}

// Tell the input relay where typing goes, on a change and every second: while it's the
// desktop, the relay grabs pass-through keyboards so SteamVR (and the Steam app with
// gamescope's focus) doesn't get the keys too. Without word from us for a few seconds,
// the relay gives the keyboards back, so a closed desktop doesn't keep them.
static char focus_control[64];
static int pointer_slot_sent = -1;

static void note_pointer_slot(struct server *s) {
    if (!s->output_names || !focus_control[0]) return;
    int slot = 0;
    if (s->pointer_focus && s->pointer_focus->index >= 0) slot = s->pointer_focus->index + 1;
    if (slot == pointer_slot_sent) return;
    pointer_slot_sent = slot;
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    if (!runtime || !runtime[0]) return;
    char path[256], tmp[280];
    snprintf(path, sizeof path, "%s/frametop-pointer-%s", runtime, focus_control);
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    fprintf(f, "%d\n", slot);
    fclose(f);
    rename(tmp, path);
}

static void keys_update(struct server *s) {
    if (!s->vr || s->beside) return;  // a test instance leaves the running desktop's keyboards alone
    // This binary is the experimental session. "keyboard hyprland" is its own focus.
    // It must not send "keyboard steam": Plasma's compositor shares that signal, and
    // a steam message from here would take the keyboard away from Plasma.
    // A Hyprland panel claims the keyboard when pointed at and retains that
    // target after leaving, until another overlay takes focus.
    const uint32_t t = now_ms();
    const bool pointed = s->output_names && s->pointer_focus != NULL;
    const bool desktop = ft_desktop_keyboard_wanted(pointed, s->keys_clicked,
                                                      ft_vr_screens_shown(), ft_vr_steam_in_front());
    if (desktop == s->keys_desktop && t - s->relay_sent < 1000) return;
    if (desktop != s->keys_desktop) wlr_log(WLR_INFO, "typing goes to %s", desktop ? "Hyprland" : "elsewhere");
    s->keys_desktop = desktop;
    s->relay_sent = t;
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    const char name[] = "frametop_relay";
    memcpy(addr.sun_path + 1, name, sizeof name - 1);
    char msg[96];
    if (s->output_names && focus_control[0])
        snprintf(msg, sizeof msg, desktop ? "keyboard hyprland %s" : "keyboard hyprland 0 %s", focus_control);
    else
        snprintf(msg, sizeof msg, "keyboard hyprland%s", desktop ? "" : " 0");
    sendto(s->relay_fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&addr,
           offsetof(struct sockaddr_un, sun_path) + 1 + sizeof name - 1);
}

// How often a screen gets its frame callback (ms; 0 every tick). KWin draws a screen only
// after its callback, and its apps wait for theirs, so this is the screen's frame rate:
// full where you look (ft_vr_screen_attention) and for a video, lower for the rest of what
// you see, and about once a second for what you don't (hidden, behind you, paused for a VR
// game). A screen nothing changes on costs nothing at any rate: KWin commits only when
// something on it moved. A remote viewer ("watch") sees every screen at full rate.
static uint32_t frame_interval(struct server *s, struct screen *sc, uint32_t t) {
    if ((int32_t)(s->watch_until - t) > 0) return 0;
    enum ft_attention a = ft_vr_screen_attention(sc->index);
    if (a == FT_IN_VIEW && (int32_t)(sc->video_until - t) > 0) a = FT_FOCUSED;
    if (a != FT_FOCUSED && t - s->typed_ms < 1500 &&
        s->seat->keyboard_state.focused_surface == sc->toplevel->base->surface)
        a = FT_FOCUSED;  // typing on it while looking elsewhere
    const int hz = s->rate[a];
    return hz > 0 ? 1000 / hz : 0;
}

static int64_t mono_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

// Ticks come once per display frame, phase_ms after its vsync: KWin gets its frame callbacks
// early in the frame and has the rest of it to draw before vrcompositor takes the panels.
// The vsync is read from SteamVR once a second, and the ticks run at absolute times between
// reads, so they keep their place (a timer set again after each tick, as before, slid
// through the frame and came about 85 times a second at 90 Hz). Without SteamVR's timing
// they still come at the display's rate (90 Hz until known). While paused, every 100 ms.
static void schedule(struct server *s) {
    const int64_t now = mono_ns();
    int64_t next;
    if (ft_vr_paused()) {
        next = now + 100000000LL;
    } else {
        double since, hz;
        if (now - s->synced_ns >= 1000000000LL) {
            s->synced_ns = now;
            if (ft_vr_vsync(&since, &hz)) {
                const int64_t period = (int64_t)(1e9 / hz);
                if (llabs(period - s->period_ns) > 100000) wlr_log(WLR_INFO, "display at %.1f Hz", hz);
                s->period_ns = period;
                s->base_ns = now - (int64_t)(since * 1e9) + (int64_t)(s->phase_ms * 1e6);
                while (s->base_ns > now) s->base_ns -= s->period_ns;
            }
        }
        next = s->base_ns + ((now - s->base_ns) / s->period_ns + 1) * s->period_ns;
    }
    struct itimerspec its = {.it_value = {.tv_sec = next / 1000000000LL, .tv_nsec = next % 1000000000LL}};
    timerfd_settime(s->tick_fd, TFD_TIMER_ABSTIME, &its, NULL);
}

// Each tick: SteamVR events, and frame callbacks for screens that committed and are due.
static int tick(int fd, uint32_t mask, void *data) {
    struct server *s = data;
    uint64_t expirations;
    const ssize_t got = read(fd, &expirations, sizeof expirations);  // clears it; how many doesn't matter
    (void)got;
    ft_vr_poll(handle_vr_event, s);
    ft_remote_tick();
    if (s->relay_buttons.held && !relay_can_press(s))
        release_relay_buttons(s, ft_vr_paused() ? "paused" : "its screen hid");
    if (++s->ticks % 9 == 0) keys_update(s);
    if (s->kb_close_at && s->ticks >= s->kb_close_at) {
        s->kb_close_at = 0;
        if (s->kb_screen >= 0) {
            ft_vr_keyboard_hide();
            s->kb_screen = -1;
        }
    }
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    const uint32_t t = now_ms();
    // Due within half a tick counts as due, so 15 Hz is every 6th tick at 90 Hz, not 7th.
    const uint32_t slack = ft_vr_paused() ? 50 : (uint32_t)(s->period_ns / 2000000);
    for (int i = 0; i < MAX_SCREENS; ++i) {
        struct screen *sc = s->screens[i];
        if (!sc || !sc->frame_pending || t - sc->frame_sent + slack < frame_interval(s, sc, t)) continue;
        sc->frame_pending = false;
        sc->frame_sent = t;
        wlr_surface_send_frame_done(sc->toplevel->base->surface, &now);
    }
    schedule(s);
    return 0;
}

static int child_exited(int sig, void *data) {
    struct server *s = data;
    int status;
    pid_t pid;
    while ((pid = waitpid(-1, &status, WNOHANG)) > 0)
        if (ft_remote_child(pid, status)) {
            continue;
        } else if (pid == s->child) {
            wlr_log(WLR_INFO, "session exited");
            wl_display_terminate(s->display);
        }
    return 0;
}

static bool key_held(const struct wlr_keyboard *kb, uint32_t code) {
    for (size_t i = 0; i < kb->num_keycodes; i++)
        if (kb->keycodes[i] == code) return true;
    return false;
}

// One key to the focused screen, through the seat's keyboard so its xkb state and
// modifiers stay right. The code is an evdev code. Hyprland's nested backend adds
// 8 itself when it turns that into an xkb keycode, so the Wayland event stays evdev.
static void send_key(struct server *s, uint32_t code, int pressed) {
    s->typed_ms = now_ms();
    struct wlr_keyboard_key_event ev = {
        .time_msec = now_ms(), .keycode = code, .update_state = true,
        .state = pressed ? WL_KEYBOARD_KEY_STATE_PRESSED : WL_KEYBOARD_KEY_STATE_RELEASED};
    wlr_keyboard_notify_key(&s->keyboard, &ev);
    wlr_seat_keyboard_notify_modifiers(s->seat, &s->keyboard.modifiers);
    wlr_seat_keyboard_notify_key(s->seat, ev.time_msec, code, ev.state);
}

// The input relay's mouse buttons (relay-buttons.h) can be pressed: the pointer is on a
// screen that shows, and nothing's paused.
static bool relay_can_press(struct server *s) {
    return s->pointer_focus && !ft_vr_paused() && ft_vr_screen_visible(s->pointer_focus->index);
}

// A mouse button from the input relay (pointer mode passes a mouse's side button through as
// a key, for Back): to the screen the pointer is on, like a laser's click, wherever typing goes.
static void relay_button(struct server *s, uint32_t code, bool pressed, char *reply, int size) {
    if (!ft_relay_button(&s->relay_buttons, code, pressed, relay_can_press(s)))
        return (void)snprintf(reply, size, pressed ? "ok no pointer, or held" : "ok not held");
    wlr_seat_pointer_notify_button(s->seat, now_ms(), code,
                                   pressed ? WL_POINTER_BUTTON_STATE_PRESSED : WL_POINTER_BUTTON_STATE_RELEASED);
    wlr_seat_pointer_notify_frame(s->seat);
    snprintf(reply, size, "ok");
}

// ...and released by us when the pointer leaves the screens, its screen hides or closes, or
// everything pauses: before the pointer leaves that screen, so KWin gets the releases.
static void release_relay_buttons(struct server *s, const char *why) {
    if (!s->relay_buttons.held) return;
    uint32_t code;
    while ((code = ft_relay_buttons_take(&s->relay_buttons))) {
        wlr_seat_pointer_notify_button(s->seat, now_ms(), code, WL_POINTER_BUTTON_STATE_RELEASED);
        wlr_log(WLR_INFO, "relay button %u released (%s)", code, why);
    }
    wlr_seat_pointer_notify_frame(s->seat);
}

// Keys from the input relay (physical keyboards): "key <evdev code> <1 press|0 release>".
// They go to the screen KWin has keyboard focus on (the last one clicked), while typing
// goes to the desktop (keys_update). The release of a key the desktop got the press for
// always goes through, or the key stays held there (a modifier held as typing moves to
// Steam would otherwise modify every key typed after it). Mouse buttons go where the
// pointer is instead (relay_button), and codes that are neither go nowhere.
static void handle_key(struct server *s, uint32_t code, int value, char *reply, int size) {
    if (value == 2) return (void)snprintf(reply, size, "ok repeat ignored");  // KWin repeats itself
    const enum ft_relay_key kind = ft_relay_key_kind(code);
    if (kind == FT_RELAY_BUTTON) {
        relay_button(s, code, value != 0, reply, size);
        return;
    }
    if (kind == FT_RELAY_DROP) return (void)snprintf(reply, size, "ok not a key or mouse button");
    // A remote screen has the typing, except for the release of a key the desktop holds.
    if (s->key_remote >= 0 && ft_remote_is(s->key_remote) && (value || !key_held(&s->keyboard, code))) {
        ft_remote_key(s->key_remote, code, value != 0);
        return (void)snprintf(reply, size, "ok remote");
    }
    if (value || !key_held(&s->keyboard, code)) {
        // A click focuses the panel. If that focus has gone, put it back on the
        // panel before dropping the key: Hyprland only acts on keys delivered
        // to its surface.
        if (s->keys_desktop && !s->seat->keyboard_state.focused_surface) {
            const int index = focused_screen(s);
            struct screen *sc = index >= 0 ? s->screens[index] : NULL;
            if (sc && sc->toplevel)
                wlr_seat_keyboard_notify_enter(s->seat, sc->toplevel->base->surface, NULL, 0, NULL);
        }
        if (!s->seat->keyboard_state.focused_surface) {
            wlr_log(WLR_INFO, "key %u dropped: the panel has no keyboard focus", code);
            return (void)snprintf(reply, size, "ok no focus");
        }
        if (!s->keys_desktop) {
            wlr_log(WLR_INFO, "key %u dropped: typing is not on this panel", code);
            return (void)snprintf(reply, size, "ok typing goes to Steam");
        }
    }
    send_key(s, code, value);
    snprintf(reply, size, "ok");
}

// Our keyboard (keyboard.cpp). The input relay sends "vrkeyboard show" when a text field
// on the desktop gets focus (and its setting allows), "vrkeyboard hide" when it loses it,
// and "vrkeyboard toggle" for a mapped button; ft-layout sends "vrkeyboard close" when it
// resets the layout. It opens for the screen KWin has keyboard focus on. A hide closes only a keyboard a text field opened, and waits a moment, so
// moving between text fields doesn't close and reopen it.
static int focused_screen(struct server *s) {
    struct wlr_surface *focus = s->seat->keyboard_state.focused_surface;
    for (int i = 0; i < MAX_SCREENS; ++i)
        if (s->screens[i] && s->screens[i]->toplevel->base->surface == focus) return i;
    if (s->pointer_focus) return s->pointer_focus->index;
    for (int i = 0; i < MAX_SCREENS; ++i)
        if (s->screens[i]) return i;
    return -1;
}

static void keyboard_command(struct server *s, const char *what, char *reply, int size) {
    const bool open = s->kb_screen >= 0;
    if (strcmp(what, "hide") == 0) {
        if (open && s->kb_auto && !s->kb_close_at) s->kb_close_at = s->ticks + 30;  // ~1/3 s
        return (void)snprintf(reply, size, "ok");
    }
    if (strcmp(what, "close") == 0) {  // however it opened, now (ft-layout apply: a reset)
        if (open) wlr_log(WLR_INFO, "keyboard closed (reset)");
        ft_vr_keyboard_hide();
        s->kb_screen = -1;
        s->kb_close_at = 0;
        return (void)snprintf(reply, size, "ok");
    }
    const bool toggle = strcmp(what, "toggle") == 0;
    if (!toggle && strcmp(what, "show") != 0) return (void)snprintf(reply, size, "error show|hide|toggle|close");
    s->kb_close_at = 0;
    if (open && toggle) {
        ft_vr_keyboard_hide();
        s->kb_screen = -1;
        return (void)snprintf(reply, size, "ok closed");
    }
    if (open) return (void)snprintf(reply, size, "ok open");
    if (!ft_vr_screens_shown()) {
        wlr_log(WLR_INFO, "keyboard not opened (%s): the screens are hidden", toggle ? "button" : "text field");
        return (void)snprintf(reply, size, "ok screens hidden");
    }
    const int screen = focused_screen(s);
    if (screen < 0 || !ft_vr_keyboard_show(screen)) {
        wlr_log(WLR_INFO, "keyboard not opened (%s) for screen %d", toggle ? "button" : "text field", screen + 1);
        return (void)snprintf(reply, size, "error not shown");
    }
    wlr_log(WLR_INFO, "keyboard open for screen %d (%s)", screen + 1, toggle ? "button" : "text field");
    s->kb_screen = screen;
    s->kb_auto = !toggle;
    snprintf(reply, size, "ok opened");
}

// A key from our keyboard, for the focused screen. Its release always goes through, so
// no key stays held.
static void panel_key(struct server *s, uint32_t code, bool pressed) {
    if (s->key_remote >= 0 && ft_remote_is(s->key_remote) && (pressed || !key_held(&s->keyboard, code))) {
        ft_remote_key(s->key_remote, code, pressed);
        return;
    }
    if (pressed ? s->seat->keyboard_state.focused_surface != NULL : key_held(&s->keyboard, code))
        send_key(s, code, pressed);
}
// Control socket: abstract datagram @ft_screens. Here: "size <screen> <w> <h>" (a new
// resolution, live), "scale <screen> <s>" (KWin's scale for it, from ft-layout),
// "toplevels" (-> "ok <count>" and a line per KWin window: "<screen> <w>x<h> <commits>
// <title>"), "input <screen> move|down|up|leave [x y [left|right|middle]]" (pointer input
// as if from that panel, x and y in its pixels; for tests, mostly with --no-vr),
// "key <code> <value>", "vrkeyboard show|hide|toggle|close" (our keyboard, from the input
// relay), and "click <overlay key>" (from the pointer helper: a mouse click landed on
// that panel, "-" for none); the rest is in vr.cpp (ft_vr_command).
static int control_readable(int fd, uint32_t mask, void *data) {
    struct server *s = data;
    char buf[512], reply[2048];
    struct sockaddr_un from;
    socklen_t len = sizeof from;
    ssize_t n;
    while ((n = recvfrom(fd, buf, sizeof buf - 1, MSG_DONTWAIT, (struct sockaddr *)&from, &len)) > 0) {
        buf[n] = 0;
        unsigned code;
        int value, index, w, h;
        double scale;
        char tail;
        if (strcmp(buf, "controller-click?") == 0) {
            snprintf(reply, sizeof reply,
                "{\"supported\":true,\"threshold\":%.3f,\"held\":%s,\"dragging\":%s,\"suppressedMotions\":%lu,\"clicks\":%lu,\"drags\":%lu}",
                s->controller_click.threshold, s->controller_click.held ? "true" : "false",
                s->controller_click.dragging ? "true" : "false", s->controller_click.suppressed,
                s->controller_click.clicks, s->controller_click.drags);
        } else if (sscanf(buf, "chord-click %d", &value) == 1) {
            ft_chord_guard_set_armed(&s->chord, value != 0);
            wlr_log(WLR_INFO, "chord-click %d", value != 0);
            snprintf(reply, sizeof reply, "ok");
        } else if (sscanf(buf, "controller-click %lf %c", &scale, &tail) == 1) {
            if (!isfinite(scale) || scale < 0 || scale > 64 || s->controller_click.buttons)
                snprintf(reply, sizeof reply, "error threshold or held controller button");
            else { s->controller_click.threshold = scale; snprintf(reply, sizeof reply, "ok"); }
        } else if (s->output_names && sscanf(buf, "claim %63s %d", reply, &index) == 2) {
            // reply is a scratch buffer here; the monitor name is copied out
            // before the reply text is written.
            char monitor[FT_OUTPUT_NAME_MAX];
            snprintf(monitor, sizeof monitor, "%s", reply);
            if (!ft_output_claim(&s->claims, monitor, index) || index > s->n_config) {
                if (index > s->n_config) ft_output_release_monitor(&s->claims, monitor);
                snprintf(reply, sizeof reply, "error claim <WAYLAND-N> <screen>");
            } else {
                consider_named(s, monitor);
                wlr_log(WLR_INFO, "claim %s -> screen %d", monitor, index);
                snprintf(reply, sizeof reply, "ok");
            }
        } else if (s->output_names && sscanf(buf, "release %63s", reply) == 1) {
            char monitor[FT_OUTPUT_NAME_MAX];
            snprintf(monitor, sizeof monitor, "%s", reply);
            ft_output_release_monitor(&s->claims, monitor);
            snprintf(reply, sizeof reply, "ok");
        } else if (s->output_names && sscanf(buf, "slot %d %d %d %lf", &index, &w, &h, &scale) == 4) {
            if (index < 1 || index > MAX_SCREENS || w < 320 || h < 200 || w > 16384 || h > 16384 ||
                !(scale >= 0.2 && scale <= 20)) {
                snprintf(reply, sizeof reply, "error slot <screen> <w> <h> <metres>");
            } else {
                if (index > s->n_config) {
                    for (int i = s->n_config; i < index; ++i)
                        if (s->config[i].width == 0) s->config[i] = (struct config){1920, 1080, 1.5};
                    s->n_config = index;
                }
                w += w & 1;
                h += h & 1;
                s->config[index - 1].width = w;
                s->config[index - 1].height = h;
                s->config[index - 1].metres = scale;
                if (s->screens[index - 1]) wlr_xdg_toplevel_set_size(s->screens[index - 1]->toplevel, w, h);
                snprintf(reply, sizeof reply, "ok");
            }
        } else if (s->output_names && strcmp(buf, "outputs") == 0) {
            int at = snprintf(reply, sizeof reply, "ok");
            for (int i = 0; i < MAX_SCREENS && at < (int)sizeof reply; ++i) {
                struct screen *sc = s->screens[i];
                if (!sc) continue;
                at += snprintf(reply + at, sizeof reply - at, "\n%d %s", i + 1, sc->monitor[0] ? sc->monitor : "-");
            }
        } else if (sscanf(buf, "size %d %d %d", &index, &w, &h) == 3) {
            // A new resolution for a screen, live: KWin resizes the screen to match. (KWin makes
            // it this size times its scale; ft-floatd sends spares' sizes divided by theirs.)
            const int min_w = index - 1 < s->n_config ? 320 : 64, min_h = index - 1 < s->n_config ? 200 : 64;
            if (index < 1 || index > MAX_SCREENS || !s->screens[index - 1] || w < min_w || h < min_h || w > 16384 ||
                h > 16384) {
                snprintf(reply, sizeof reply, "error bad screen or size");
            } else {
                // A screen's size is even: KWin's nested backend gives a scaled screen a whole
                // buffer scale (1.5 -> 2), and a buffer that isn't a multiple of it is a protocol
                // error that disconnects KWin. (ft-floatd rounds spares' sizes for their scale.)
                if (index - 1 < s->n_config) w += w & 1, h += h & 1;
                if (index - 1 < s->n_config) s->config[index - 1].width = w, s->config[index - 1].height = h;
                wlr_xdg_toplevel_set_size(s->screens[index - 1]->toplevel, w, h);
                snprintf(reply, sizeof reply, "ok");
            }
        } else if (sscanf(buf, "scale %d %lf", &index, &scale) == 2) {
            if (index < 1 || index > MAX_SCREENS || !(scale >= 0.25 && scale <= 8)) {
                snprintf(reply, sizeof reply, "error bad screen or scale");
            } else {
                if (s->scale[index - 1] != scale) wlr_log(WLR_INFO, "screen %d: KWin scale %g", index, scale);
                s->scale[index - 1] = scale;
                snprintf(reply, sizeof reply, "ok");
            }
        } else if (sscanf(buf, "key %u %d", &code, &value) == 2) {
            handle_key(s, code, value, reply, sizeof reply);
            len = sizeof from;
            continue;  // no reply: keys are fire-and-forget
        } else if (strncmp(buf, "vrkeyboard ", 11) == 0) {
            keyboard_command(s, buf + 11, reply, sizeof reply);
        } else if (strncmp(buf, "input ", 6) == 0) {
            char what[8] = "", button[8] = "left";
            double x = 0, y = 0;
            const int got = sscanf(buf, "input %d %7s %lf %lf %7s", &index, what, &x, &y, button);
            struct ft_event e = {.screen = index - 1, .x = x, .y = y, .button = BTN_LEFT};
            if (strcmp(button, "right") == 0) e.button = BTN_RIGHT;
            else if (strcmp(button, "middle") == 0) e.button = BTN_MIDDLE;
            if (got >= 2 && strcmp(what, "leave") == 0) e.type = FT_LEAVE;
            else if (got >= 4 && strcmp(what, "move") == 0) e.type = FT_MOTION;
            else if (got >= 4 && (strcmp(what, "down") == 0 || strcmp(what, "up") == 0))
                e.type = FT_BUTTON, e.pressed = what[0] == 'd';
            else index = 0;
            if ((index < 1 || index > MAX_SCREENS || !s->screens[index - 1]) && !ft_remote_is(index - 1)) {
                snprintf(reply, sizeof reply, "error input <screen> move|down|up|leave [x y [button]]");
            } else {
                handle_vr_event(&e, s);
                snprintf(reply, sizeof reply, "ok");
            }
        } else if (sscanf(buf, "watch %d", &value) == 1) {
            // A remote viewer is watching for that many seconds (vnc-bridge.sh renews it).
            s->watch_until = now_ms() + (uint32_t)(value < 0 ? 0 : value > 60 ? 60 : value) * 1000;
            snprintf(reply, sizeof reply, "ok");
        } else if (sscanf(buf, "rates %d %d %d", &index, &w, &h) == 3) {
            // Frame rates in Hz: focused, in view, hidden (0: every display frame).
            if (index < 0 || w < 0 || h < 0 || index > 240 || w > 240 || h > 240) {
                snprintf(reply, sizeof reply, "error rates <focused> <in view> <hidden> (Hz, 0 full)");
            } else {
                s->rate[FT_FOCUSED] = index, s->rate[FT_IN_VIEW] = w, s->rate[FT_HIDDEN] = h;
                wlr_log(WLR_INFO, "frame rates: focused %d, in view %d, hidden %d (0 full)", index, w, h);
                snprintf(reply, sizeof reply, "ok");
            }
        } else if (sscanf(buf, "phase %lf", &scale) == 1) {
            // Ticks this long after the vsync (ms), for tuning.
            if (!(scale >= 0 && scale < 20)) snprintf(reply, sizeof reply, "error phase <ms after vsync>");
            else s->phase_ms = scale, s->synced_ns = 0, snprintf(reply, sizeof reply, "ok");
        } else if (strcmp(buf, "rates?") == 0) {
            // "ok <focused> <in view> <hidden> <display Hz> <phase ms> <watched>" and a line per
            // screen: "<screen> hidden|view|focused <ms between frames> <video 0|1>".
            static const char *names[] = {"hidden", "view", "focused"};
            const uint32_t t = now_ms();
            int at = snprintf(reply, sizeof reply, "ok %d %d %d %.1f %.1f %d", s->rate[FT_FOCUSED],
                              s->rate[FT_IN_VIEW], s->rate[FT_HIDDEN], 1e9 / s->period_ns, s->phase_ms,
                              (int32_t)(s->watch_until - t) > 0);
            for (int i = 0; i < MAX_SCREENS && at < (int)sizeof reply; ++i) {
                struct screen *sc = s->screens[i];
                if (!sc) continue;
                at += snprintf(reply + at, sizeof reply - at, "\n%d %s %u %d", i + 1,
                               names[ft_vr_screen_attention(i)], frame_interval(s, sc, t),
                               (int32_t)(sc->video_until - t) > 0);
            }
        } else if (strcmp(buf, "toplevels") == 0) {
            int n = 0, at = 0;
            for (int i = 0; i < MAX_SCREENS; ++i) n += s->screens[i] != NULL;
            at = snprintf(reply, sizeof reply, "ok %d", n);
            for (int i = 0; i < MAX_SCREENS && at < (int)sizeof reply; ++i) {
                const struct screen *sc = s->screens[i];
                if (!sc) continue;
                at += snprintf(reply + at, sizeof reply - at, "\n%d %dx%d %u %s", i + 1, sc->buffer_width,
                               sc->buffer_height, sc->commits, sc->toplevel->title ? sc->toplevel->title : "");
            }
        } else if (strncmp(buf, "click ", 6) == 0) {
            // A click on another panel takes typing to Steam. Our own panels (the screens,
            // their controls) leave it: a click on a screen arrives as a panel event.
            if (strcmp(buf + 6, "-") != 0 && strncmp(buf + 6, "frametop.", 9) != 0) s->keys_clicked = false;
            len = sizeof from;
            continue;
        } else if (strcmp(buf, "debug") == 0) {
            // ft-screens' side of scripts/report.sh's debug line; vr.cpp adds SteamVR's.
            char vr[1024] = "ok vr=off";
            if (s->vr) ft_vr_command("debug", vr, sizeof vr);
            snprintf(reply, sizeof reply, "%s kb_screen=%d kb_auto=%d typing=%s focused_screen=%d pointer_screen=%d",
                     vr, s->kb_screen + 1, s->kb_auto ? 1 : 0,
                     s->key_remote >= 0 ? "remote" : s->keys_desktop ? "desktop" : s->keys_clicked ? "desktop (hidden)" : "steam",
                     focused_screen(s) + 1, s->pointer_focus ? s->pointer_focus->index + 1 : 0);
        } else if (!ft_remote_command(buf, reply, sizeof reply)) {
            ft_vr_command(buf, reply, sizeof reply);
        }
        if (len > offsetof(struct sockaddr_un, sun_path))
            sendto(fd, reply, strlen(reply), MSG_DONTWAIT, (struct sockaddr *)&from, len);
        len = sizeof from;
    }
    return 0;
}

static int open_control_socket(const char *name) {
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    const size_t len = strlen(name);
    if (len == 0 || len >= sizeof addr.sun_path - 1) {
        wlr_log(WLR_ERROR, "bad control socket name");
        close(fd);
        return -1;
    }
    memcpy(addr.sun_path + 1, name, len);
    if (bind(fd, (struct sockaddr *)&addr, offsetof(struct sockaddr_un, sun_path) + 1 + len) != 0) {
        wlr_log(WLR_ERROR, "can't bind @%s (another ft-screens running?)", name);
        close(fd);
        return -1;
    }
    return fd;
}

static int stop(int sig, void *data) {
    wl_display_terminate(((struct server *)data)->display);
    return 0;
}

// ---------------------------------------------------------------- setup

static void keyboard_led(struct wlr_keyboard *kb, uint32_t leds) {}
static const struct wlr_keyboard_impl keyboard_impl = {.name = "ft-screens-keyboard", .led_update = keyboard_led};

static bool setup_dmabuf(struct server *s) {
    struct stat st;
    const char *node = "/dev/dri/renderD128";
    if (stat(node, &st) != 0) {
        wlr_log(WLR_ERROR, "no %s", node);
        return false;
    }
    struct wlr_linux_dmabuf_feedback_v1 fb = {.main_device = st.st_rdev};
    wl_array_init(&fb.tranches);
    struct wlr_linux_dmabuf_feedback_v1_tranche *tr = wlr_linux_dmabuf_feedback_add_tranche(&fb);
    tr->target_device = st.st_rdev;
    const uint32_t formats[] = {DRM_FORMAT_XRGB8888, DRM_FORMAT_ARGB8888};
    for (size_t f = 0; f < 2; ++f) {
        uint64_t mods[64];
        const int n = ft_vr_modifiers(formats[f], mods, 64);
        for (int i = 0; i < n; ++i) wlr_drm_format_set_add(&tr->formats, formats[f], mods[i]);
        wlr_log(WLR_INFO, "dmabuf: format 0x%x, %d modifiers SteamVR can import", formats[f], n);
    }
    struct wlr_linux_dmabuf_v1 *dmabuf = wlr_linux_dmabuf_v1_create(s->display, 4, &fb);
    wlr_linux_dmabuf_feedback_v1_finish(&fb);
    return dmabuf != NULL;
}

int main(int argc, char **argv) {
    struct server s = {0};
    ft_output_table_init(&s.claims);
    const char *output_names = getenv("FT_OUTPUT_NAMES");
    s.output_names = output_names && strcmp(output_names, "1") == 0;
    // About 0.9 degrees on a 3.4 m wide 3440-pixel screen 2 m away; 8 (the first default,
    // about 0.2 degrees) needed a very still hand to click (headset test 2026-10-03).
    s.controller_click.threshold = 32;
    for (int i = 0; i < MAX_SCREENS; ++i) s.scale[i] = 1;
    s.kb_screen = -1;
    s.key_remote = -1;
    s.rate[FT_FOCUSED] = 0, s.rate[FT_IN_VIEW] = 15, s.rate[FT_HIDDEN] = 1;
    s.period_ns = 1000000000LL / 90;
    s.phase_ms = 1;
    const char *socket_name = "ft-screens-0", *control_name = "ft_screens";
    char **command = NULL;
    s.vr = true;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_name = argv[++i];
        } else if (strcmp(argv[i], "--control") == 0 && i + 1 < argc) {
            control_name = argv[++i];
            snprintf(focus_control, sizeof focus_control, "%s", control_name);
        } else if (strcmp(argv[i], "--spares") == 0 && i + 1 < argc) {
            s.spares = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--no-vr") == 0) {
            s.vr = false;
        } else if (strcmp(argv[i], "--beside") == 0) {
            s.beside = true;
        } else if (strcmp(argv[i], "--rates") == 0 && i + 1 < argc) {
            if (sscanf(argv[++i], "%d,%d,%d", &s.rate[FT_FOCUSED], &s.rate[FT_IN_VIEW], &s.rate[FT_HIDDEN]) != 3) {
                fprintf(stderr, "bad --rates %s (want FOCUSED,IN_VIEW,HIDDEN in Hz, 0 full)\n", argv[i]);
                return 2;
            }
        } else if (strcmp(argv[i], "--screen") == 0 && i + 1 < argc && s.n_config < MAX_SCREENS) {
            struct config *c = &s.config[s.n_config];
            c->metres = 0;
            if (sscanf(argv[++i], "%dx%d@%lf", &c->width, &c->height, &c->metres) < 2) {
                fprintf(stderr, "bad --screen %s (want WxH@METRES)\n", argv[i]);
                return 2;
            }
            if (c->metres <= 0) c->metres = 1.5 * c->width / 1920.0;
            ++s.n_config;
        } else if (strcmp(argv[i], "--") == 0) {
            command = &argv[i + 1];
            break;
        } else {
            fprintf(stderr,
                    "usage: %s [--socket NAME] [--control NAME] [--no-vr] [--beside] [--screen WxH@METRES]... "
                    "[--spares N] [--rates F,V,H] [-- COMMAND ARGS...]\n",
                    argv[0]);
            return 2;
        }
    }
    if (s.n_config == 0) s.config[s.n_config++] = (struct config){3440, 1440, 2.4};

    setvbuf(stdout, NULL, _IOLBF, 0);  // vr.cpp prints to stdout; keep it in order with the log
    wlr_log_init(WLR_INFO, NULL);
    if (s.vr && !ft_vr_init()) return 1;
    if (s.beside) ft_vr_beside();
    if (!s.vr) wlr_log(WLR_INFO, "--no-vr: running without SteamVR");

    s.display = wl_display_create();
    s.loop = wl_display_get_event_loop(s.display);
    ft_remote_init(s.loop, s.vr);
    wl_list_init(&s.buffers);
    wlr_compositor_create(s.display, 6, NULL);
    wlr_subcompositor_create(s.display);
    const uint32_t shm_formats[] = {DRM_FORMAT_ARGB8888, DRM_FORMAT_XRGB8888};  // wlroots wants DRM codes
    wlr_shm_create(s.display, 1, shm_formats, 2);
    if (!setup_dmabuf(&s)) return 1;
    wlr_data_device_manager_create(s.display);

    // Aquamarine 0.15.1 (Hyprland's nested Wayland backend) binds xdg_wm_base v6.
    // wlroots 0.20 implements the protocol; v3 made that client disconnect on bind.
    // Keep testing KWin and input behavior after this version upgrade.
    s.xdg_shell = wlr_xdg_shell_create(s.display, 6);
    s.new_toplevel.notify = new_toplevel;
    wl_signal_add(&s.xdg_shell->events.new_toplevel, &s.new_toplevel);
    s.decoration = wlr_xdg_decoration_manager_v1_create(s.display);
    s.new_decoration.notify = new_decoration;
    wl_signal_add(&s.decoration->events.new_toplevel_decoration, &s.new_decoration);

    s.seat = wlr_seat_create(s.display, "seat0");
    wlr_keyboard_init(&s.keyboard, &keyboard_impl, "ft-screens-keyboard");
    struct xkb_context *xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    struct xkb_keymap *keymap = xkb_keymap_new_from_names(xkb, NULL, XKB_KEYMAP_COMPILE_NO_FLAGS);
    wlr_keyboard_set_keymap(&s.keyboard, keymap);
    xkb_keymap_unref(keymap);
    xkb_context_unref(xkb);
    wlr_seat_set_keyboard(s.seat, &s.keyboard);
    wlr_seat_set_capabilities(s.seat, WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD);

    if (wl_display_add_socket(s.display, socket_name) != 0) {
        wlr_log(WLR_ERROR, "can't create socket %s (another ft-screens?)", socket_name);
        return 1;
    }
    char path[256];
    snprintf(path, sizeof path, "%s/%s", getenv("XDG_RUNTIME_DIR") ? getenv("XDG_RUNTIME_DIR") : "/tmp", socket_name);
    wlr_log(WLR_INFO, "listening on %s; %d screen(s) configured, %d spare(s)", path, s.n_config, s.spares);

    const int control = open_control_socket(control_name);
    if (control < 0) return 1;
    s.relay_fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    wl_event_loop_add_fd(s.loop, control, WL_EVENT_READABLE, control_readable, &s);

    s.tick_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    s.base_ns = mono_ns();
    s.tick = wl_event_loop_add_fd(s.loop, s.tick_fd, WL_EVENT_READABLE, tick, &s);
    schedule(&s);
    wl_event_loop_add_signal(s.loop, SIGINT, stop, &s);
    wl_event_loop_add_signal(s.loop, SIGTERM, stop, &s);
    wl_event_loop_add_signal(s.loop, SIGCHLD, child_exited, &s);

    if (command && command[0]) {
        s.child = fork();
        if (s.child == 0) {
            setenv("WAYLAND_DISPLAY", path, 1);
            execvp(command[0], command);
            perror(command[0]);
            _exit(127);
        }
    }

    // Ahead of the desktop's programs for the CPU, after the session started (it would
    // inherit it): KWin waits for our ticks to draw. SteamOS lets users go to nice -8
    // (RLIMIT_NICE 28) once they raise their soft limit; without that, as before.
    if (s.vr) {
        struct rlimit rl;
        if (getrlimit(RLIMIT_NICE, &rl) == 0 && rl.rlim_cur < rl.rlim_max) {
            rl.rlim_cur = rl.rlim_max;
            setrlimit(RLIMIT_NICE, &rl);
        }
        if (setpriority(PRIO_PROCESS, 0, -5) != 0) wlr_log(WLR_INFO, "can't raise our priority (nice -5); running at 0");
    }

    wl_display_run(s.display);

    wlr_log(WLR_INFO, "stopping");
    // SteamVR first, while every buffer the panels show still exists (KWin's and the remote
    // streams'): vrcompositor leaves standby the moment we disconnect, and twice it drew a
    // remote panel's texture that was already gone (SIGBUS, 2026-10-07).
    ft_vr_shutdown();
    ft_remote_shutdown();
    if (s.child > 0) kill(s.child, SIGTERM);
    wl_display_destroy_clients(s.display);
    // wlroots asserts that nothing still listens to its globals when they go.
    wl_list_remove(&s.new_toplevel.link);
    wl_list_remove(&s.new_decoration.link);
    wl_display_destroy(s.display);
    return 0;
}
