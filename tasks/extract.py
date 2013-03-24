from pdfminer.pdfparser import PDFParser, PDFDocument
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter, process_pdf
from pdfminer.converter import TextConverter, HTMLConverter
from pdfminer.layout import LAParams, LTText, LTTextBoxHorizontal
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfdevice import PDFDevice
import re, math
from collections import defaultdict

rsrcmgr = PDFResourceManager()
laparams = LAParams()

#divide between page number boxes and text
XDIVIDE = 149

#maximum acceptable distance in y values between two corresponding boxes. 
MARGIN = 3

#pixels per &nbsp;
SPACE = 5

def serialize_pdf_item(item):
    return {
        'x0': item.x0,
        'y0': item.y0,
        'x1': item.x1,
        'y1': item.y1,
        'text': item.get_text()
    }

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

    #roadmap will contain markers to section headers
    roadmap = {}
    for page in enumerate(doc.get_pages()):
        print "<------------", (page[0] + 1)
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
            #we can optionally catch everything else here
            '''
            else:
                extra.append(item)
            '''
            
        # now we need to match them up
        # MARGIN is the acceptable distance in y values between two boxes to still decide they correspond to one another
        lines = defaultdict(list)
        for number in line_numbers:
            c = 0
            while c < len(line_text):
                if abs(number.y0 - line_text[c].y0) <= MARGIN: #and abs(number.y1 - line_text[c].y1) <= MARGIN:
                    lines[number.get_text().strip()].append(line_text[c])                    
                    del line_text[c]
                else:
                    c += 1

        # this will contain new lines we discover -- see below
        extras = {}
                    
        # sort text elements in the line by x pos, and indent according to first element's x position
        for line in lines:
            lines[line] = sorted(lines[line], key=lambda x: x.x0)
            # store multiline nodes
            previous = [x for x in lines[line] if len(x.get_text().split('\n')) > 2]
            
            prefix = "&nbsp;" * int(math.floor((lines[line][0].x0 - XDIVIDE) / SPACE))
            lines[line] = prefix + " ".join([x.get_text().strip().split('\n')[-1] for x in lines[line]])

            # if we don't have anything for the previous line, put multiline nodes here. Mainly useful for TITLE TK \n SUBHEAD \n etc
            if line != '1' and str(int(line) - 1) not in lines:
                extras[str(int(line) - 1)] = " ".join([x.get_text().strip().split('\n')[-2] for x in previous])

        #print extras
        lines = dict(lines.items() + extras.items())

        # look for roadmap matches
        for line in lines:
            if re.search("TITLE [IVXL]+", lines[line]):
                roadmap[re.search("TITLE [IVXL]+", lines[line]).group(0)] = [page[0] + 1, line]

        text[page[0] + 1] = lines
        
    return {
        "text": text,
        "roadmap": roadmap
    }
