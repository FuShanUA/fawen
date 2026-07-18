import win32com.client
import os

# Use the safe copy created earlier to avoid source path encoding issues
SOURCE_PATH = r"/Users/shanfu/cc/hardsubber/input.pptx"
DESKTOP_PATH = r"d:\desktop" # Explicit user path
BASE_NAME = "Palantir_Picture"
PPTX_OUT = os.path.join(DESKTOP_PATH, f"{BASE_NAME}.pptx")
PDF_OUT = os.path.join(DESKTOP_PATH, f"{BASE_NAME}.pdf")

def main():
    print(f"Source: {SOURCE_PATH}")
    print(f"Output Directory: {DESKTOP_PATH}")

    ppt_app = None
    try:
        # Connect to PowerPoint
        ppt_app = win32com.client.gencache.EnsureDispatch("PowerPoint.Application")
        ppt_app.Visible = 1 # msoTrue

        # 1. Open Source
        print("Opening source presentation...")
        # Open(FileName, ReadOnly, Untitled, WithWindow)
        pres = ppt_app.Presentations.Open(SOURCE_PATH, ReadOnly=1, Untitled=0, WithWindow=1)

        # 2. Save as Picture Presentation
        # ppSaveAsOpenXMLPicturePresentation = 36
        print(f"Saving as native Picture PPTX to {PPTX_OUT}...")
        pres.SaveAs(PPTX_OUT, 36)

        # Close Original
        pres.Close()

        # 3. Open the creating Picture PPTX to convert to PDF
        # This ensures the PDF reflects the picture version exactly
        print("Opening generated Picture PPTX...")
        pic_pres = ppt_app.Presentations.Open(PPTX_OUT, ReadOnly=1, Untitled=0, WithWindow=1)

        print(f"Saving as PDF to {PDF_OUT}...")
        # ppSaveAsPDF = 32
        pic_pres.SaveAs(PDF_OUT, 32)

        pic_pres.Close()
        print("Done.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()