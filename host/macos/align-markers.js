// Shows the markers Frametop's monitor alignment finds a display by: four AprilTags (36h11), placed as
// fractions of the screen so its resolution and scaling don't matter. align/solver.cpp has the same layout.
// Sunshine runs this as the app FrametopAlign and ends it when the headset quits the app.
// Usage: osascript -l JavaScript align-markers.js DISPLAY_KEY FIRST_TAG_ID [SECONDS]
ObjC.import('AppKit');
ObjC.import('CoreGraphics');

const TAG = 0.43, MARGIN = 0.056, QUIET = 0.031;
// Each tag's six rows of six cells, 1 white, inside its black border.
const CODES = '21a146bab 92d18fe9b 7089014bb 193979e27 44153d3d7 35cd5b8cf a10ba56a0 2b874a608 b57fb8d44 4e20b5a64 61d897f2c ab3469ffc 594ca45c2 fa1c2d2e2 97c24b972 75928624a 1caafe99a 3236ddc16 884e527d6 5771a8c7e f52925b81 2e59cc1a1 7fa58ab31 eb43384f9 3913d5345 d79b1a3b5 0dfbe768d 5cd7a031d b9c8f7a4b 46987e06b 6e0c5d527 5bc567bb4'.split(' ');

// The display with this key (vendor-model-serial, -2 and up for identical monitors), as displays.js makes it.
function screenWithKey(key) {
  const screens = $.NSScreen.screens;
  const rows = [];
  for (let i = 0; i < screens.count; i++) {
    const screen = screens.objectAtIndex(i);
    const id = ObjC.unwrap(screen.deviceDescription.objectForKey('NSScreenNumber'));
    rows.push({ screen, x: screen.frame.origin.x, y: screen.frame.origin.y,
                base: [$.CGDisplayVendorNumber(id), $.CGDisplayModelNumber(id), $.CGDisplaySerialNumber(id)].join('-') });
  }
  rows.sort((a, b) => a.x - b.x || a.y - b.y);
  const seen = {};
  for (const r of rows) {
    seen[r.base] = (seen[r.base] || 0) + 1;
    if ((seen[r.base] === 1 ? r.base : r.base + '-' + seen[r.base]) === key) return r.screen;
  }
  return null;
}

function fill(color, x, y, w, h) {
  color.set;
  $.NSRectFill($.NSMakeRect(x, y, w, h));
}

function draw(width, height, firstId) {
  const image = $.NSImage.alloc.initWithSize($.NSMakeSize(width, height));
  image.lockFocus;
  const black = $.NSColor.blackColor, white = $.NSColor.whiteColor;
  fill(black, 0, 0, width, height);
  const side = TAG * height, edge = MARGIN * height, quiet = QUIET * height;
  // Reading order, with y counted down from the top; Cocoa's y runs up.
  const places = [[edge, edge], [width - edge - side, edge], [edge, height - edge - side], [width - edge - side, height - edge - side]];
  places.forEach(([x, top], t) => {
    const yUp = height - top - side;
    fill(white, x - quiet, yUp - quiet, side + 2 * quiet, side + 2 * quiet);
    fill(black, x, yUp, side, side);
    const bits = BigInt('0x' + CODES[firstId + t]);
    const cell = side / 8;
    for (let row = 0; row < 6; row++)
      for (let col = 0; col < 6; col++)
        if ((bits >> BigInt(35 - (row * 6 + col))) & 1n)
          fill(white, x + (col + 1) * cell, yUp + side - (row + 2) * cell, cell, cell);
  });
  image.unlockFocus;
  return image;
}

function run(argv) {
  const [key, firstId, seconds] = [argv[0], Number(argv[1]), Number(argv[2] || 360)];
  if (firstId + 4 > CODES.length) throw new Error('no tags for first id ' + firstId);
  $.NSApplication.sharedApplication.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
  const screen = screenWithKey(key);
  if (!screen) throw new Error('no display with key ' + key);
  const frame = screen.frame;
  const window = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(frame, 0, $.NSBackingStoreBuffered, false);
  window.level = 1000;     // above the menu bar and the Dock
  window.opaque = true;
  window.ignoresMouseEvents = true;
  const view = $.NSImageView.alloc.initWithFrame($.NSMakeRect(0, 0, frame.size.width, frame.size.height));
  view.imageScaling = $.NSImageScaleAxesIndependently;
  view.image = draw(frame.size.width, frame.size.height, firstId);
  window.contentView = view;
  window.setFrameDisplay(frame, true);
  window.orderFrontRegardless;
  $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(seconds));  // a last resort: Sunshine ends it
}
