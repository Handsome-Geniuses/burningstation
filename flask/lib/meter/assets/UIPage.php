<?php
$ROOT      = '/var/volatile/html';
$MODE_FILE = $ROOT . '/.ui_mode';
$STOCK_UI  = $ROOT . '/UI_0.html';
$CFG_FILE  = $ROOT . '/ui_overlay.json';
$RESULTS_FILE = $ROOT . '/results.json';

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
    echo '<style>'
        . 'html,body{margin:0!important;padding:0!important;width:100%!important;height:100%!important;overflow:hidden!important}'
        . '#apriltag-overlay{position:fixed;top:0;left:0;width:100vw;height:100vh;background:#ffffff;'
        . 'z-index:2147483647;display:flex;align-items:center;justify-content:center;pointer-events:none}'
        . '#apriltag-overlay img{width:100vmin;height:100vmin;max-width:100vw;max-height:100vh;'
        . 'object-fit:contain;display:block;image-rendering:pixelated;image-rendering:crisp-edges}'
        . '</style>'
        . '<div id="apriltag-overlay"><img src="' . htmlspecialchars($src, ENT_QUOTES) . '" alt="apriltag"></div>';
}
function overlay_results() {
    $p = '/var/volatile/html/results.json';
    $j = is_readable($p) ? @json_decode(file_get_contents($p), true) : null;

    echo '<style>
      #results-overlay {
        position: fixed; top: 0; right: 0;
        width: 50vw; height: 100vh;
        background: rgba(255,255,255,.95);
        z-index: 2147483647; overflow-y: auto;
        padding: 0 20px 20px; box-sizing: border-box;
        font: 14px/1.4 system-ui, sans-serif; color: #000;
        pointer-events: none;
      }
      #results-header {
        text-align: center; font-size: 42px; font-weight: 700;
        padding: 16px 12px; margin: 0 -20px 24px -20px;
        color: #fff; text-shadow: 1px 1px 3px rgba(0,0,0,.4);
        border-bottom: 4px solid rgba(0,0,0,.2);
      }
      #results-header.pass  { background: #006400; }
      #results-header.fail  { background: #B22222; animation: pulse 2s infinite; }
      #results-header.na,
      #results-header.default { background: #555; }
      @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .88; } }

      .main-header {
        font-size: 20px; font-weight: 700;
        margin: 24px 0 12px; padding-bottom: 6px;
        border-bottom: 2px solid #ccc;
      }
      .sub-header {
        font-size: 16px; font-weight: 700;
        margin: 16px 0 6px; padding-bottom: 4px;
        border-bottom: 1px solid #eee;
      }

      .result-item { display: flex; margin: 4px 0; align-items: baseline; }
      .result-item .key {
        font-weight: 700; min-width: 160px; flex-shrink: 0;
        text-align: right; padding-right: 10px;
      }
      .result-item .value { flex: 1; color: #333; word-break: break-word; }
      .value.pass { color: #006400; }
      .value.fail { color: #B22222; }
      .value.na   { color: #555; }

      .test-grid {
        display: grid; grid-template-columns: 1fr 1fr;
        grid-template-rows: auto auto 1fr; gap: 0 28px; margin-top: 8px;
      }
      .test-column { display: contents; }
      .test-column > .main-header { grid-row: 1; }
      .test-column > .device-results-section { grid-row: 2; }
      .test-column > .other-info-section { grid-row: 3; padding-top: 16px; }

      @media (max-width: 900px) {
        .test-grid { grid-template-columns: 1fr; grid-template-rows: auto; gap: 32px; }
        .test-column > * { grid-row: auto; }
      }
      
      .other-info-section .result-item {
        margin-left: 20px;
      }
      .other-info-section .result-item .key {
        text-align: left;
        min-width: 0;
        flex: 0 0 auto;
        padding-right: 5px;
      }
    </style>
    <div id="results-overlay">';

    if (!is_array($j)) {
        echo '<p class="no-results">No results available</p></div>';
        return;
    }

    $r = isset($j['overall_result']) ? strtoupper(trim($j['overall_result'])) : 'N/A';
    $o = htmlspecialchars($r);
    $c = $r === 'PASS' ? 'pass' : ($r === 'FAIL' ? 'fail' : ($r === 'N/A' ? 'na' : 'default'));

    echo '<div id="results-header" class="' . $c . '">'
       . ($r === 'PASS' ? '✓ ' : ($r === 'FAIL' ? '✗ ' : ''))
       . 'Results: ' . $o . '</div>';

    $l = function($items) {
        if (empty($items) || !is_array($items)) return;
        foreach ($items as $k => $v) {
            $cls = '';
            $lv = strtolower($v);
            if (strpos($lv, 'pass') !== false || $lv === 'ok') $cls = 'pass';
            elseif (strpos($lv, 'fail') !== false || $lv === 'error') $cls = 'fail';
            elseif ($lv === 'n/a' || $lv === 'skip') $cls = 'na';
            echo '<div class="result-item"><span class="key">'
               . htmlspecialchars($k) . ':</span><span class="value ' . $cls . '">'
               . htmlspecialchars($v) . '</span></div>';
        }
    };

    if (!empty($j['meter_info'] ?? [])) {
        echo '<h2 class="main-header">Meter Info</h2>';
        $l($j['meter_info']);
    }

    $pa = $j['passive'] ?? []; $ph = $j['physical'] ?? [];
    if (!empty($pa) || !empty($ph)) {
        echo '<div class="test-grid">';
        foreach (['passive' => $pa, 'physical' => $ph] as $type => $data) {
            if (empty($data)) continue;
            $title = ucfirst($type) . ' Tests';
            echo '<div class="test-column"><h2 class="main-header">' . $title . '</h2>';
            echo '<div class="device-results-section">';
            if (!empty($data['device_results'] ?? [])) {
                echo '<h3 class="sub-header">Device Results</h3>';
                $l($data['device_results']);
            }
            echo '</div><div class="other-info-section">';
            if (!empty($data['other_info'] ?? [])) {
                echo '<h3 class="sub-header">Other Info</h3>';
                $l($data['other_info']);
            }
            echo '</div></div>';
        }
        echo '</div>';
    }

    echo '</div>';
}

// --- determine mode ---
$mode = is_readable($MODE_FILE) ? trim(file_get_contents($MODE_FILE)) : 'stock';
$mode = strtolower($mode);

// --- defaults ---
$cfg = [
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
    case 'results':
        stream_stock($STOCK_UI);
        overlay_results();
        break;
    case 'stock':
    default:
        stream_stock($STOCK_UI);
        break;
}
