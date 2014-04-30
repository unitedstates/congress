import bill_info


def open_bill(bill_id):
    return open("test/fixtures/bills/%s/information.html" % bill_id).read()


def bill(bill_id):
    return bill_info.parse_bill(bill_id, open_bill(bill_id), {})
