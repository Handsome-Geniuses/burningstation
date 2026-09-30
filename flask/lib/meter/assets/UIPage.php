<?php
$ROOT      = '/var/volatile/html';
$MODE_FILE = $ROOT . '/.ui_mode';
$STOCK_UI  = $ROOT . '/UI_0.html';
$CFG_FILE  = $ROOT . '/ui_overlay.json';
$BANNER_FILE = $ROOT . '/banner.json';
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
function banner_text($base, $path) {
    $j = is_readable($path) ? @json_decode(file_get_contents($path), true) : null;
    $suffix = is_array($j) && isset($j['text']) && is_string($j['text'])
        ? trim($j['text'])
        : '';

    return $suffix === '' ? $base : $base . ' - ' . strtoupper($suffix);
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
      #results-overlay{position:fixed;top:0;right:0;width:50vw;height:100vh;background:rgba(255,255,255,.96);z-index:2147483647;overflow-y:auto;padding:0 16px 14px;box-sizing:border-box;font:13px/1.25 system-ui,sans-serif;color:#000;pointer-events:none}
      #results-header{text-align:center;font-size:34px;font-weight:700;padding:10px 8px;margin:0 -16px 12px;color:#fff;text-shadow:1px 1px 3px rgba(0,0,0,.4);border-bottom:3px solid rgba(0,0,0,.2)}
      #results-header.pass{background:#006400}#results-header.fail{background:#B22222;animation:pulse 2s infinite}#results-header.na,#results-header.default{background:#555}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.88}}
      .main-header{font-size:18px;font-weight:700;margin:12px 0 6px;padding-bottom:4px;border-bottom:2px solid #ccc}.sub-header{font-size:14px;font-weight:700;margin:9px 0 3px;padding-bottom:3px;border-bottom:1px solid #ddd}
      .result-item{display:flex;margin:3px 0;align-items:baseline}.result-item .key{font-weight:700;min-width:116px;flex-shrink:0;text-align:right;padding-right:7px}.result-item .value{flex:1;color:#333;word-break:break-word}.value.pass{color:#006400}.value.fail{color:#B22222}.value.na{color:#555}
      #meter-info{display:grid;grid-template-columns:1fr 1fr;column-gap:12px}#meter-info .result-item .key{min-width:0;text-align:left}.test-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:6px}.test-panel{min-width:0}.test-panel.operator{grid-column:1/-1}.test-panel .result-item .key{min-width:0;text-align:left;flex:0 0 auto}.device-results-section .result-item,.runtime-section .result-item{margin-left:8px}
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

    $l = function($items, $limit = 0, $colorize = true) {
        if (empty($items) || !is_array($items)) return;
        foreach ($items as $k => $v) {
            $v = is_scalar($v) || $v === null ? (string)$v : json_encode($v);
            if ($limit && strlen($v) > $limit) $v = substr($v, 0, $limit - 3) . '...';
            $cls = '';
            $lv = strtolower($v);
            if ($colorize && (strpos($lv, 'pass') !== false || $lv === 'ok')) $cls = 'pass';
            elseif ($colorize && (strpos($lv, 'fail') !== false || $lv === 'error')) $cls = 'fail';
            elseif ($colorize && ($lv === 'n/a' || $lv === 'skip')) $cls = 'na';
            echo '<div class="result-item"><span class="key">'
               . htmlspecialchars($k) . ':</span><span class="value ' . $cls . '">'
               . htmlspecialchars($v) . '</span></div>';
        }
    };

    if (!empty($j['meter_info'] ?? [])) {
        echo '<h2 class="main-header">Meter Info</h2><div id="meter-info">';
        $l($j['meter_info']);
        echo '</div>';
    }

    $panel = function($type, $data, $single = false) use ($l) {
        if (empty($data) || !is_array($data)) return;
        $other = is_array($data['other_info'] ?? null) ? $data['other_info'] : [];
        $error = array_key_exists('Error', $other) ? $other['Error'] : 'None'; unset($other['Error']);
        echo '<div class="test-panel' . ($single ? ' operator' : '') . '"><h2 class="main-header">' . htmlspecialchars($type) . ' Tests</h2>';
        if (!empty($data['device_results'] ?? [])) { echo '<div class="device-results-section"><h3 class="sub-header">Device Results</h3>'; $l($data['device_results']); echo '</div>'; }
        echo '<div class="runtime-section"><h3 class="sub-header">Runtime Data</h3>'; $l(['Error' => $error], 400, false); $l($other, 160, false); echo '</div>';
        echo '</div>';
    };
    $op = $j['operator'] ?? []; $pa = $j['passive'] ?? []; $ph = $j['physical'] ?? [];
    if (!empty($op)) { echo '<div class="test-grid">'; $panel('Operator', $op, true); echo '</div>'; }
    elseif (!empty($pa) || !empty($ph)) { echo '<div class="test-grid">'; $panel('Passive', $pa); $panel('Physical', $ph); echo '</div>'; }

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
        overlay_banner(banner_text($cfg['banner'], $BANNER_FILE)); // append after so it’s on top
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
