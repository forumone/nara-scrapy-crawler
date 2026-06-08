import re

from scrapy.selector import Selector
from w3lib.html import remove_tags_with_content


class ArchiveSpiderMixin:
    # min_offset skips the first N chars before searching for a sentence boundary,
    # avoiding false splits on abbreviations like "Mr." or "U.S."
    @staticmethod
    def _teaser(text, min_offset=60, max_len=200, truncate_after=False, ellipsis=False):
        if not text:
            return ''
        m = re.search(r'[.!?](?=\s+[A-Z])', text[min_offset:])
        result = text[:min_offset + m.end()] if m else text
        suffix = '…' if ellipsis else ''
        if len(result) <= max_len:
            return result + suffix
        if truncate_after:
            next_space = result.find(' ', max_len)
            truncated = result[:next_space] if next_space != -1 else result
        else:
            truncated_raw = result[:max_len]
            last_space = truncated_raw.rfind(' ')
            truncated = truncated_raw[:last_space] if last_space > 0 else truncated_raw
        return truncated + suffix

    def _extract_text(self, response, selector):
        match = response.css(selector).get()
        if not match:
            return ''
        try:
            cleaned = remove_tags_with_content(match, which_ones=('script', 'style'))
        except TypeError:
            cleaned = ''
        text = Selector(text=cleaned).xpath('string(.)').get(default='')
        return re.sub(r'\s+', ' ', text).strip()
