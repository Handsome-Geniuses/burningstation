<?php
// UIPage.php (minimal + toggleable)
// Modes via /var/volatile/html/.ui_mode: "stock", "banner", "charuco", "apriltag"

$ROOT      = '/var/volatile/html';
$MODE_FILE = $ROOT . '/.ui_mode';
$STOCK_UI  = $ROOT . '/UI_0.html';
$CFG_FILE  = $ROOT . '/ui_overlay.json';

// --- tiny helpers ---
function stream_stock($p) {
    $fp = @fopen($p, "r");
    if ($fp) { fpassthru($fp); fclose($fp); }
    else { echo "<pre>Unable to open UI_0.html</pre>"; }
}
function overlay_banner($text) {
    echo '<div style="position:fixed;top:0;left:0;right:0;background:#111;color:#ffd966;'
       . 'padding:6px;z-index:2147483647;text-align:center;font:14px/1.2 -apple-system,'
       . 'BlinkMacSystemFont,Segoe UI,Arial,sans-serif">'
       . htmlspecialchars($text, ENT_QUOTES) . '</div>';
}
function overlay_charuco_fullscreen($src, $bg) {
    echo '<!doctype html>';
    echo '<meta charset="utf-8">';
    echo '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">';
    echo '<title>Charuco</title>';
    echo '<style>body {margin:0;padding:0;}</style>';  // Ensure no default margins
    echo '<link rel="preload" as="image" href="'.htmlspecialchars($src, ENT_QUOTES).'">';
    echo '<div style="position:fixed;inset:0;z-index:2147483647;'
       . 'background:'.htmlspecialchars($bg,ENT_QUOTES).';'
       . 'display:flex;align-items:center;justify-content:center;">'
       . '<img src="'.htmlspecialchars($src,ENT_QUOTES).'" alt="charuco" '
       . 'style="width:100vw;height:100vh;object-fit:contain;image-rendering:pixelated;image-rendering:crisp-edges;display:block;">'
       . '</div>';
}
function overlay_apriltag_fullscreen($src) {
    echo '
    <style>
      html, body {
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        height: 100% !important;
        overflow: hidden !important;
      }

      #apriltag-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;

        background: #ffffff;

        z-index: 2147483647;

        display: flex;
        align-items: center;
        justify-content: center;

        pointer-events: none;
      }

      #apriltag-overlay img {
        width: 100vmin;
        height: 100vmin;

        max-width: 100vw;
        max-height: 100vh;

        object-fit: contain;
        display: block;

        image-rendering: pixelated;
        image-rendering: crisp-edges;
      }
    </style>

    <div id="apriltag-overlay">
      <img src="' . htmlspecialchars($src, ENT_QUOTES) . '" alt="apriltag">
    </div>
    ';
}

// --- determine mode ---
$mode = is_readable($MODE_FILE) ? trim(file_get_contents($MODE_FILE)) : 'stock';
$mode = strtolower($mode);

// --- defaults (JSON optional) ---
$cfg = [
    // Absolute web path so nothing can rewrite it
    'image'  => '/content/Images/charuco.png',
    'bg'     => '#ffffff',
    'banner' => 'BURN-IN MODE – DO NOT UNPLUG',
    'apriltag' => '/content/Images/apriltag.png'
];
if (is_readable($CFG_FILE)) {
    $json = json_decode(@file_get_contents($CFG_FILE), true);
    if (is_array($json)) { $cfg = array_merge($cfg, $json); }
}
// Normalize images to absolute web path if needed
if (isset($cfg['image']) && strpos($cfg['image'], '/') !== 0) {
    $cfg['image'] = '/' . ltrim($cfg['image'], '/');
}
if (isset($cfg['apriltag']) && strpos($cfg['apriltag'], '/') !== 0) {
    $cfg['apriltag'] = '/' . ltrim($cfg['apriltag'], '/');
}

// Fresh HTML per request so mode switches take effect; image stays cached by URL
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store, must-revalidate');
header('Pragma: no-cache');

switch ($mode) {
    case 'banner':   // overlay_banner over stock
        stream_stock($STOCK_UI);
        overlay_banner($cfg['banner']); // append after so it’s on top
        break;

    case 'charuco':  // overlay_charuco (append the real UI after charuco so that requests.get() still see its content)
        overlay_charuco_fullscreen($cfg['image'], $cfg['bg']);
        stream_stock($STOCK_UI);
        break;

    case 'apriltag':
        stream_stock($STOCK_UI);
        overlay_apriltag_fullscreen($cfg['apriltag']);
        break;

    case 'stock':
    default:
        stream_stock($STOCK_UI);
        break;
}
