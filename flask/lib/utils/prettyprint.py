#=================================================
# File: prettyprint.py
# Developer: nosnhoj
# Desc: printing with color!
#=================================================
import re

class STYLE:
	RESET			= 1<<0
	BOLD			= 1<<1
	DIM				= 1<<2
	UNDERLINE		= 1<<4
	BLINK			= 1<<5
	INVERTED 		= 1<<7
	HIDDEN 			= 1<<8
	STRIKETHROUGH	= 1<<9

def __hex_rgb(s):
    if not re.match(r'^#([0-9A-Fa-f]{6})$', s): raise ValueError("Invalid color. Must be #RRGGBB")
    s = s.lstrip('#')
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)     
def __hex_rgb_fg(s):
	r,g,b = __hex_rgb(s)
	return f"38;2;{r};{g};{b}"
def __hex_rgb_bg(s):
	r,g,b = __hex_rgb(s)
	return f"48;2;{r};{g};{b}"
def __stylish(val):
	return ';'.join([str(i) for i in range(val.bit_length()) if (val >> i) & 1])

def prettify(s,fg=None,bg=None,style=None):
	# individual formatting
	fg=__hex_rgb_fg(fg) if fg else ''
	bg=__hex_rgb_bg(bg) if bg else ''
	st = __stylish(style) if style else ''

	# combining
	if fg==bg==st: code = ''
	else: code = f"\033[{';'.join([w for w in [fg,bg,st] if w])}m"

	return f"{code}{s}\033[0m"

__print = print
def print(*objects, sep=None, end=None, file=None, flush=False,fg:str=None, bg:str=None, style:int=None):
	s = f"{' '.join([str(o) for o in objects])}"
	s = prettify(s,fg,bg,style)
	end = end and prettify(end,fg,bg,style)
	__print(s,sep=sep,end=end,file=file,flush=flush)



if __name__ == "__main__":
	print(" FG=RED, BG=GREEN, BOLD+UNDERLINE", fg="#ff0000", bg="#00ff00", style=STYLE.BOLD|STYLE.UNDERLINE)