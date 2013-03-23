from pdfminer.pdfparser import PDFParser, PDFDocument
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter, process_pdf
from pdfminer.converter import TextConverter, HTMLConverter
from pdfminer.layout import LAParams, LTText, LTTextBoxHorizontal
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfdevice import PDFDevice
import re

rsrcmgr = PDFResourceManager()
laparams = LAParams()

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
        interpreter.process_page(page[1])
        layout = device.get_result()
        line_numbers = []
        lines = []
        for item in layout:
            print item
            if isinstance(item, LTTextBoxHorizontal):
                if re.sub("[\s\d]+", "", item.get_text()) == "":
                    line_numbers.append(item.get_text().strip())
                else:
                    if len(line_numbers) > 0:
                        lines.append((line_numbers[0], item.get_text()))
                        line_numbers.pop(0)
        text[page[0]] = lines
    return text
                        
