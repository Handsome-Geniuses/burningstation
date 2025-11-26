from lib.meter.ssh_meter import SSHMeter
import os
import sys
if getattr(sys, "frozen", False): _dir = os.path.dirname(sys.executable)
else: _dir = os.path.dirname(__file__)

def send_fun_meter(meter:SSHMeter, force=True):
    path_volatile = "/var/volatile"
    path_vhtml = os.path.join(path_volatile, "html/")
    fp_vuipage = os.path.join(path_vhtml, "UIPage.php")
    local_cat = os.path.normpath(os.path.join(_dir, "../../../next/public/running-cat.gif"))
    remote_cat = "/var/volatile/html/running-cat.gif"

    # cat
    with open(local_cat, 'rb') as f: file_data = f.read()
    meter.connect()
    
    code,out,err = meter.exec_parse(f'test -f {remote_cat} && echo "1" || echo "0"')
    if out== "0":
        with meter.get_transport().open_session() as channel:
            channel.exec_command(f'cat > {remote_cat}')
            channel.sendall(file_data)


    # UIPage.php
    content="""\
<?php
$html = file_get_contents("UI_0.html");

$overlay = <<<HTML
<style>
    #overlay {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 9999;
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
        pointer-events: none;
    }
    #overlay img {
        height: 70%;
        object-fit: cover;
        object-position: center;
    }
</style>
<div id="overlay">
    <img src="running-cat.gif" alt="">
</div>
HTML;

$html = str_replace('</body>', $overlay . "\n</body>", $html);
echo $html;
?>\
"""
    cmd = f"cat << 'EOF' > {fp_vuipage}\n{content}\nEOF"\
        if force else \
        f"[ ! -f {fp_vuipage} ] && printf %s '{content}' > {fp_vuipage}"
    code, out, err = meter.exec_parse(cmd)


