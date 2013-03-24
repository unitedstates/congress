from pdfminer.pdfparser import PDFParser, PDFDocument
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter, process_pdf
from pdfminer.converter import TextConverter, HTMLConverter
from pdfminer.layout import LAParams, LTText, LTTextBoxHorizontal
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfdevice import PDFDevice
import re

rsrcmgr = PDFResourceManager()
laparams = LAParams()

XDIVIDE = 149
MARGIN = 3

#see http://www.unixuser.org/~euske/python/pdfminer/programming.html#layout
#take the PDF of the bill and return a generator for each page
def get_text_from_pdf(filename):
    fp = file(filename, 'rb')
    parser = PDFParser(fp)
    doc = PDFDocument()
    parser.set_document(doc)
    doc.set_parser(parser)
    doc.initialize('')
    device = PDFDevice(rsrcmgr)
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)

    #page numbers are given in LTTextLineHorizontal objects
    #borrowing some ideas from https://github.com/euske/pdfminer/blob/master/pdfminer/converter.py
    text = {}    
    for page in enumerate(doc.get_pages()):
        #print "<------------", (page[0] + 1)
        interpreter.process_page(page[1])
        layout = device.get_result()

        #we're going to build two lists, one of line numbers and one of text corresponding to those line numbers
        line_numbers = []
        line_text = []
        
        for item in [x for x in layout if isinstance(x, LTTextBoxHorizontal)]:
            #print item
            # if it's an LTTextBoxHorizontal, left of 150px and a digit, it's (hopefully) a line number
            if item.x0 < XDIVIDE and re.sub("[\s\d]+", "", item.get_text()) == "":
                line_numbers.append(item)
            # else if it's on the other side of the xdivide, add to candidates for lines of text
            elif item.x0 >= XDIVIDE:
                line_text.append(item)

        # now we need to match them up
        # MARGIN is the acceptable distance in y values between two boxes to still decide they correspond to one another
        lines = []
        for number in line_numbers:
            for c in range(len(line_text)):
                if abs(number.y0 - line_text[c].y0) <= MARGIN and abs(number.y1 - line_text[c].y1) <= MARGIN:
                    #print number.y0 - line_text[c].y0
                    lines.append((number.get_text().strip(), line_text[c].get_text().strip()))
                    del line_text[c]
                    break
        #print lines
        text[page[0] + 1] = lines
    return text
