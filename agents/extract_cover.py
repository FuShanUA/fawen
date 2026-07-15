import fitz
import sys

pdf_path = r"/Users/shanfu/cc/Projects/data-governance-in-the-age-of-generative-ai/source/2024年11月5日_亚马逊云科技_生成式AI时代的数据治理_v1.pdf"
output_path = r"/Users/shanfu/cc/Library/Tools/postfdry/cover_preview.png"

doc = fitz.open(pdf_path)
page = doc.load_page(0) # First page
pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Higher resolution
pix.save(output_path)
doc.close()

print(f"Cover preview saved to {output_path}")