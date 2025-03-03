import re, time
from modules import util
from modules.util import Failed

logger = util.logger

builders = ["letterboxd_list", "letterboxd_list_details"]
base_url = "https://letterboxd.com"

class Letterboxd:
    def __init__(self, config):
        self.config = config

    def _parse_list(self, list_url, language):
        if self.config.trace_mode:
            logger.debug(f"URL: {list_url}")
        response = self.config.get_html(list_url, headers=util.header(language))
        letterboxd_ids = response.xpath("//li[contains(@class, 'poster-container') or contains(@class, 'film-detail')]/div/@data-film-id")
        items = []
        for letterboxd_id in letterboxd_ids:
            slugs = response.xpath(f"//div[@data-film-id='{letterboxd_id}']/@data-film-slug")
            notes = response.xpath(f"//div[@data-film-id='{letterboxd_id}']/parent::li/div[@class='film-detail-content']/div/p/text()") if list_url.endswith(("/detail", "/detail/")) else None
            ratings = response.xpath(f"//div[@data-film-id='{letterboxd_id}']/parent::li/div[@class='film-detail-content']//span[contains(@class, 'rating')]/@class") if list_url.endswith(("/detail", "/detail/")) else None
            years = response.xpath(f"//div[@data-film-id='{letterboxd_id}']/parent::li/div[@class='film-detail-content']/h2/small/a/text()") if list_url.endswith(("/detail", "/detail/")) else None
            rating = None
            if ratings:
                match = re.search("rated-(\\d+)", ratings[0])
                if match:
                    rating = int(match.group(1))
            items.append((letterboxd_id, slugs[0], int(years[0]) if years else None, notes[0] if notes else None, rating))
        next_url = response.xpath("//a[@class='next']/@href")
        if len(next_url) > 0:
            time.sleep(2)
            items.extend(self._parse_list(f"{base_url}{next_url[0]}", language))
        return items

    def _tmdb(self, letterboxd_url, language):
        if self.config.trace_mode:
            logger.debug(f"URL: {letterboxd_url}")
        response = self.config.get_html(letterboxd_url, headers=util.header(language))
        ids = response.xpath("//a[@data-track-action='TMDb']/@href")
        if len(ids) > 0 and ids[0]:
            if "themoviedb.org/movie" in ids[0]:
                return util.regex_first_int(ids[0], "TMDb Movie ID")
            raise Failed(f"Letterboxd Error: TMDb Movie ID not found in {ids[0]}")
        raise Failed(f"Letterboxd Error: TMDb Movie ID not found at {letterboxd_url}")

    def get_list_description(self, list_url, language):
        if self.config.trace_mode:
            logger.debug(f"URL: {list_url}")
        response = self.config.get_html(list_url, headers=util.header(language))
        descriptions = response.xpath("//meta[@property='og:description']/@content")
        return descriptions[0] if len(descriptions) > 0 and len(descriptions[0]) > 0 else None

    def validate_letterboxd_lists(self, err_type, letterboxd_lists, language):
        valid_lists = []
        for letterboxd_dict in util.get_list(letterboxd_lists, split=False):
            if not isinstance(letterboxd_dict, dict):
                letterboxd_dict = {"url": letterboxd_dict}
            dict_methods = {dm.lower(): dm for dm in letterboxd_dict}
            final = {
                "url": util.parse(err_type, "url", letterboxd_dict, methods=dict_methods, parent="letterboxd_list").strip(),
                "note": util.parse(err_type, "note", letterboxd_dict, methods=dict_methods, parent="letterboxd_list") if "note" in dict_methods else None,
                "rating": util.parse(err_type, "rating", letterboxd_dict, methods=dict_methods, datatype="int", parent="letterboxd_list", maximum=100, range_split="-") if "rating" in dict_methods else None,
                "year": util.parse(err_type, "year", letterboxd_dict, methods=dict_methods, datatype="int", parent="letterboxd_list", minimum=1000, maximum=3000, range_split="-") if "year" in dict_methods else None
            }
            if not final["url"].startswith(base_url):
                raise Failed(f"{err_type} Error: {final['url']} must begin with: {base_url}")
            elif not self._parse_list(final["url"], language):
                raise Failed(f"{err_type} Error: {final['url']} failed to parse")
            valid_lists.append(final)
        return valid_lists

    def get_tmdb_ids(self, method, data, language):
        if method == "letterboxd_list":
            logger.info(f"Processing Letterboxd List: {data}")
            items = self._parse_list(data["url"], language)
            total_items = len(items)
            if total_items > 0:
                ids = []
                filtered_ids = []
                for i, item in enumerate(items, 1):
                    letterboxd_id, slug, year, note, rating = item
                    filtered = False
                    if data["year"]:
                        start_year, end_year = data["year"].split("-")
                        if not year or int(end_year) < year or year < int(start_year):
                            filtered = True
                    if data["rating"]:
                        start_rating, end_rating = data["rating"].split("-")
                        if not rating or int(end_rating) < rating or rating < int(start_rating):
                            filtered = True
                    if data["note"]:
                        if not note or data["note"] not in note:
                            filtered = True
                    if filtered:
                        filtered_ids.append(slug)
                        continue
                    logger.ghost(f"Finding TMDb ID {i}/{total_items}")
                    tmdb_id = None
                    expired = None
                    if self.config.Cache:
                        tmdb_id, expired = self.config.Cache.query_letterboxd_map(letterboxd_id)
                    if not tmdb_id or expired is not False:
                        try:
                            tmdb_id = self._tmdb(f"{base_url}{slug}", language)
                        except Failed as e:
                            logger.error(e)
                            continue
                        if self.config.Cache:
                            self.config.Cache.update_letterboxd_map(expired, letterboxd_id, tmdb_id)
                    ids.append((tmdb_id, "tmdb"))
                logger.info(f"Processed {total_items} TMDb IDs")
                if filtered_ids:
                    logger.info(f"Filtered: {filtered_ids}")
                return ids
            else:
                raise Failed(f"Letterboxd Error: No List Items found in {data}")
        else:
            raise Failed(f"Letterboxd Error: Method {method} not supported")
