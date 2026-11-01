# The laptop's interactive shell, using this desktop's generated colors.
if status is-interactive
    set fish_greeting
    if test "$TERM" != linux; and command -sq starship
        function starship_transient_prompt_func
            starship module character
        end
        starship init fish | source
        enable_transience
    end
    set -l terminal_colors "$XDG_STATE_HOME/quickshell/user/generated/terminal/sequences.txt"
    if test -f "$terminal_colors"
        cat "$terminal_colors"
    end
    alias clear "printf '\033[2J\033[3J\033[1;1H'"
    alias celar clear
    alias claer clear
    alias q 'qs -c ii'
    if test "$TERM" != linux; and command -sq eza
        alias ls 'eza --icons=auto'
    end
    if test "$TERM" = xterm-kitty; and command -sq kitten
        alias ssh 'kitten ssh'
    end
end
