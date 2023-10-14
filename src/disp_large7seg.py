from disp_base import DisplayBase
from luma.core.device import device
from luma.core.render import canvas
from PIL import ImageFont,Image, ImageOps


class Large7SegDisplay(DisplayBase):

	fontFile = "resources/DSEG7ClassicMini-Bold.ttf"
	SEG_LENGTH = 18
	SEG_WIDTH = 3
	
	COLON_SIZE = 3
	COLON_COLOR = 8

	PM_X = (SEG_LENGTH + SEG_LENGTH + 10) * 2 + 27
	PM_Y = SEG_LENGTH * 2 - 5
	
	DIGIT_OFS = [
		[0, 0],
		[SEG_LENGTH + 10, 0],
		[(SEG_LENGTH + 10) * 2 + 9, 0],
		[(SEG_LENGTH + 10) * 3 + 9, 0]
	]

	COLON_OFS = [
		[(SEG_LENGTH + 8) * 2 + 4, int(SEG_LENGTH / 2) + 2],
		[(SEG_LENGTH + 8) * 2 + 4, SEG_LENGTH + int(SEG_LENGTH / 2)]
	]


	def __init__(self, device: device):
		self.device = device
					
	def _draw_colon(self, xofs, yofs, config):
		for num in range(2):
			x = Large7SegDisplay.COLON_OFS[num][0]
			y = Large7SegDisplay.COLON_OFS[num][1]
			self._window.DrawBox(x + xofs, y + yofs, Large7SegDisplay.COLON_SIZE,
				Large7SegDisplay.COLON_SIZE,
				config['brightness'])

	def _draw_digit(self, xofs, yofs, num, value,config):

					# clockwise from top: a,b,c,d,e,f, and g in middle

		segs = Large7SegDisplay.SEVEN_SEGS[value]

		x = Large7SegDisplay.DIGIT_OFS[num][0]
		y = Large7SegDisplay.DIGIT_OFS[num][1]


	def get_window_size(self):
					return (132, 40)

	def make_time(self, xofs, yofs, hours, minutes, _seconds, config):

		if config['am_pm']:
			pm = (hours>=12)
			if hours > 12:
				hours = hours - 12                

		hours_a = int(hours / 10)
		hours_b = int(hours % 10)
		mins_a = int(minutes / 10)
		mins_b = int(minutes % 10)

		font=ImageFont.truetype(self.fontFile, 40)
		text=f"{hours_a}{hours_b}:{mins_a}{mins_b}"
		with canvas(self.device) as draw:
			x = (draw.im.size[0]-font.getsize(text)[0])/2
			y = (draw.im.size[1]-font.getsize(text)[1])/2
 
			wifi = ImageOps.invert( Image.open("resources/no-wifi.mono.png" ))
			draw.bitmap([10,10], wifi
							 .resize([int(0.1 * s) for s in wifi.size]), fill=1 )
			draw.text(
				stroke_width=0, 
				fill=1,
				align='left',
				text=text,
				xy=[x, y],
				font=font)

