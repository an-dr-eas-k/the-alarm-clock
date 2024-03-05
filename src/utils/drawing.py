from PIL import ImageDraw, Image
from PIL.ImageFont import FreeTypeFont

def get_concat_h(im1, im2):
	height = max(im1.height, im2.height)
	dst = Image.new('RGBA', (im1.width + im2.width, height), (0, 0, 0, 0))
	y=int(( height - im1.height ) / 2)
	dst.paste(im1, (0, y))
	y=int(( height - im2.height ) / 2)
	dst.paste(im2, (im1.width, y))
	return dst

def get_concat_v(im1, im2):
	width = max(im1.width, im2.width)
	dst = Image.new('RGBA', (width, im1.height + im2.height), (0, 0, 0, 0))
	x=int(( width - im1.width ) / 2)
	dst.paste(im1, (x, 0))
	x=int(( width - im2.width ) / 2)
	dst.paste(im2, (x, im1.height))
	return dst

def get_concat_h_multi_blank(im_list):
	_im = im_list.pop(0)
	for im in im_list:
			_im = get_concat_h(_im, im)
	return _im

def text_to_image(
	text: str,
	font: FreeTypeFont,
	fg_color,
	bg_color = 'black',
	mode: str = 'RGB',
):
   box = font.getbbox(text)
   img = Image.new(mode, (box[2]-box[0], box[3]-box[1]), bg_color)
   ImageDraw.Draw(img).text([-box[0],-box[1]], text, font=font, fill=fg_color)
   return img

def grayscale_to_color(grayscale_value: int):
		return (grayscale_value << 16) | (grayscale_value << 8) | grayscale_value