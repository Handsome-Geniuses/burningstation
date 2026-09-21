from lib.meter.ssh_meter import SSHMeter
import os
import sys
if getattr(sys, "frozen", False): _dir = os.path.dirname(sys.executable)
else: _dir = os.path.dirname(__file__)

def send_msg_meter(meter: SSHMeter, msg:str="hello world", force=True):
    path_volatile = "/var/volatile"
    path_vhtml = os.path.join(path_volatile, "html/")
    fp_vuipage = os.path.join(path_vhtml, "UIPage.php")

    meter.connect()

    # New simple UIPage.php content
    content = f"""<?php
$html = file_get_contents("UI_0.html");

$overlay = <<<HTML
<style>
    #overlay {{
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 9999;
        display: flex;
        justify-content: center;
        align-items: center;
        font-size: 5em;
        font-weight: bold;
        color: red;
        pointer-events: none;
        opacity: 0.3
    }}
</style>
<div id="overlay">
    {msg}
</div>
HTML;

$html = str_replace('</body>', $overlay . "\\n</body>", $html);
echo $html;
?>"""

    # Write the PHP file remotely
    cmd = f"cat << 'EOF' > {fp_vuipage}\n{content}\nEOF" if force else \
          f"[ ! -f {fp_vuipage} ] && printf %s '{content}' > {fp_vuipage}"
    
    code, out, err = meter.exec_parse(cmd)

if __name__ == "__main__":
    meter = SSHMeter("192.168.137.192")
    send_msg_meter(meter, meter.host)
    meter.force_diagnostics()
