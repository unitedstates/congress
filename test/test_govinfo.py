import unittest

from congress.tasks import govinfo


class GovinfoOptions(unittest.TestCase):

    def test_comma_separated_collections(self):
        self.assertEqual(govinfo.collection_list({"bulkdata": "FR,BILLSTATUS"}, "bulkdata"), ["BILLSTATUS", "FR"])

    def test_missing_or_empty_option(self):
        self.assertEqual(govinfo.collection_list({}, "bulkdata"), [])
        self.assertEqual(govinfo.collection_list({"bulkdata": ""}, "bulkdata"), [])
        self.assertEqual(govinfo.collection_list({"bulkdata": "BILLS,"}, "bulkdata"), ["BILLS"])

    def test_false_means_no_collections(self):
        # usc-run govinfo --collections=BILLS --bulkdata=False
        self.assertEqual(govinfo.collection_list({"bulkdata": False}, "bulkdata"), [])

    def test_bare_flag_is_a_clear_error(self):
        # usc-run govinfo --collections
        with self.assertRaises(ValueError) as cm:
            govinfo.collection_list({"collections": True}, "collections")
        self.assertIn("--collections=", str(cm.exception))

    def test_run_with_bulkdata_false(self):
        urls = []
        original = govinfo.update_sitemap
        govinfo.update_sitemap = lambda url, *args: urls.append(url)
        try:
            govinfo.run({"collections": "BILLS", "bulkdata": False})
        finally:
            govinfo.update_sitemap = original
        self.assertEqual(urls, [govinfo.COLLECTION_SITEMAPINDEX_PATTERN.format(collection="BILLS")])
