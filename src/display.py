import datetime
import os
from luma.core.device import device
from luma.core.render import canvas
from PIL import ImageFont,Image, ImageOps

from domain import AlarmClockState, Config, Observer


class Display(Observer):

	resourcesDir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"
	fontFile = f"{resourcesDir}/DSEG7ClassicMini-Bold.ttf"
	noWifiFile = f"{resourcesDir}/no-wifi.mono.png" 

	device: device
	alarmClockState: AlarmClockState

	def __init__(self, device: device, state: AlarmClockState):
		self.device = device
		self.alarmClockState = state
		self.alarmClockState.registerObserver(self)

	def notify(self, propertyName, propertyValue):
		super().notify(propertyName, propertyValue)
		self.adjustDisplay()
					
	def adjustDisplay(self):

		font=ImageFont.truetype(self.fontFile, 40)
		config = self.alarmClockState.configuration

		now = datetime.datetime.now()
		blinkSegment = " "
		if (self.alarmClockState.displayContent.showBlinkSegment):
			blinkSegment = config.blinkSegment

		self.alarmClockState.displayContent.showBlinkSegment = not self.alarmClockState.displayContent.showBlinkSegment

		text=now.strftime(config.clockFormatString.replace("<blinkSegment>", blinkSegment))
		fontBBox = font.getbbox(text)
		width = fontBBox[2] - fontBBox[0]
		height = fontBBox[3] - fontBBox[1]
		with canvas(self.device) as draw:
			x = (draw.im.size[0]-width)/2
			y = (draw.im.size[1]-height)/2
 
			wifi = ImageOps.invert( Image.open( self.noWifiFile ))
			draw.bitmap([10,10], wifi
							 .resize([int(0.05 * s) for s in wifi.size]), fill=1 )
			draw.text(
				stroke_width=0, 
				fill=1,
				align='left',
				text=text,
				xy=[x, y],
				font=font)

