
import io
from cairosvg import svg2png
from svglib.svglib import svg2rlg, SvgRenderer
from reportlab.graphics.renderPM import drawToPIL
from weasyprint import HTML

svg_code = """
		<svg xmlns="http://www.w3.org/2000/svg" width="265" height="64" viewBox="0 0 265 64" fill="black" stroke="#000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10"/>
				<line x1="12" y1="8" x2="12" y2="12"/>
				<line x1="12" y1="16" x2="12" y2="16"/>
		</svg>
"""

svg_code_with_font = """
<svg xmlns="http://www.w3.org/2000/svg" width="265" height="64" xmlns:xlink="http://www.w3.org/1999/xlink">
	<defs>
		<font-face font-family="blabla">
			<font-face-src>
				<font-face-uri xlink:href="/home/andreask/own/development/raspberry-workspace/the-alarm-clock/the-alarm-clock/src/resources/DSEG7Classic-Regular.ttf" />
			</font-face-src>
		</font-face>
	</defs>
	<text font-family="blabla" font-size="12" x="12" y="12">08:15 This doesn't work unfortunately</text>
</svg>
"""

def convert_using_cairosvg():

	svg2png(bytestring=svg_code,write_to='output.png')
	svg2png(bytestring=svg_code_with_font,write_to='output_with_font.png')

def convert_using_reportlab(svg_string):
	svg_io = io.StringIO(svg_string)
	drawing = svg2rlg(svg_io)
	pil_image = drawToPIL(drawing)
	pil_image.save('output.png')


def convert_using_weasyprint(svg_string):
	HTML(string=svg_string).write_png('output.pdf')
	

if __name__ == '__main__':
	convert_using_reportlab(svg_code)
