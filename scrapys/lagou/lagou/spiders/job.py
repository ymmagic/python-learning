# -*- coding: utf-8 -*-
import json
import uuid

import scrapy
from scrapy.http import Request, FormRequest

from scrapys.nearjob import app, items, sql, enums
from utils import mytime


class JobSpider(scrapy.Spider):
    name = 'job'
    allowed_domains = ['www.lagou.com', 'api.map.baidu.com']

    # start_urls = ['https://www.lagou.com/jobs/positionAjax.json']

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.postgres = app.postgres()
        self.city_list = self.postgres.fetch_all(sql.get_city())
        self.job_list = self.postgres.fetch_all(sql.get_job())
        self.start = 'https://www.lagou.com/jobs/positionAjax.json?px=default&needAddtionalResult=false&city={}'
        self.referer = 'https://www.lagou.com/jobs/list_{}'
        self.source_url = 'https://www.lagou.com/jobs/{}.html'
        self.company_logo = 'https://www.lgstatic.com/thumbnail_120x120/{}'
        self.headers = {
            'Host': 'www.lagou.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/69.0.3497.100 Safari/537.36',
        }

    def start_requests(self):
        for kd in self.job_list:
            job_id, job_name, boss_code, tb_name = kd
            for city in self.city_list:
                city_id, form_city, city_code = city
                form_data = {'first': 'true', 'pn': '1', 'kd': job_name}
                self.headers['Cookie'] = self.random_cookie()
                self.headers['Referer'] = self.referer.format(job_name)
                meta = {'city_id': city_id, 'city': form_city, 'job_name': job_name,
                        'job_id': job_id, 'tb_name': tb_name}
                yield FormRequest(self.start.format(form_city), formdata=form_data, callback=self.parse,
                                  headers=self.headers, meta=meta)

    def parse(self, response):
        self.logger.warning(response)
        resp = json.loads(response.body_as_unicode())
        self.logger.info(resp)
        success = resp.get('success')
        self.logger.info('1. resp code %s success %s' % (resp.get('code'), success))
        if success:
            job_name, job_id = response.meta['job_name'], response.meta['job_id']
            tb_name, city, city_id = response.meta['tb_name'], response.meta['city'], response.meta['city_id']

            content = resp['content']
            page_no = content['pageNo']
            page_size = content['pageSize']
            position_result = content['positionResult']
            total_count = position_result['totalCount']
            if page_no * page_size < total_count:
                # 判断和抓取下一页数据
                next_page_no = str(page_no + 1)
                form_data = {'first': 'false', 'pn': next_page_no, 'kd': job_name}
                self.headers['Cookie'] = self.random_cookie()
                self.headers['Referer'] = self.referer.format(job_name)
                meta = {'city_id': city_id, 'city': city, 'job_name': job_name, 'job_id': job_id, 'tb_name': tb_name}
                yield FormRequest(self.start.format(city), formdata=form_data, callback=self.parse,
                                  headers=self.headers, meta=meta)

            result_list = position_result['result']
            self.logger.info('2. result_list %s', len(result_list))
            for result in result_list:
                # 解析数据并抓取详情
                item = items.JobItem()

                item['source_from'] = enums.SourceType.lagou.value
                item['city'], item['city_id'] = city, city_id
                item['job_id'], item['tb_name'] = job_id, tb_name
                position_id = result.get('positionId')
                item['position_id'] = str(position_id)
                item['job_name'] = result.get('positionName')
                item['job_salary'] = result.get('salary')
                item['job_experience'] = result.get('workYear')
                item['job_education'] = result.get('education')
                item['job_advantage'] = result.get('positionAdvantage')
                position_labels = result.get('positionLables')
                if position_labels:
                    item['job_label'] = json.dumps(position_labels, ensure_ascii=False)
                item['post_job_time'] = mytime.str_to_date(result.get('createTime'))
                item['company_id'] = str(result.get('companyId'))
                item['company_short_name'] = result.get('companyShortName')
                item['company_full_name'] = result.get('companyFullName')
                latitude = result.get('latitude')
                longitude = result.get('longitude')
                item['company_latitude'] = float(latitude) if latitude else .0
                item['company_longitude'] = float(longitude) if longitude else .0
                item['company_finance'] = result.get('financeStage')
                item['company_industry'] = result.get('industryField')
                item['company_scale'] = result.get('companySize')
                business_zones = result.get('businessZones')
                if business_zones:
                    item['company_zone'] = json.dumps(business_zones, ensure_ascii=False)
                source_url = self.source_url.format(position_id)
                item['source_url'] = source_url
                item['company_logo'] = self.company_logo.format(result.get('companyLogo'))

                self.headers['Referer'] = ''
                yield Request(source_url, meta={'item': item},
                              headers=self.headers, callback=self.parse_detail)

    def parse_detail(self, response):
        item = response.meta['item']

        description = response.xpath('//dd[@class="job_bt"]/div/p/text()').extract()
        item['job_description'] = '\n'.join(map(str.strip, description))
        work_address = response.xpath('//div[@class="work_addr"]/a[not(@id="mapPreview")]/text()').extract()
        work_address_detail = response.xpath('//input[@name="positionAddress"]/@value').extract_first()
        address = '{0}{1}'.format(''.join(work_address), work_address_detail)
        item['company_location'] = address
        item['company_index'] = response.xpath('//ul[@class="c_feature"]/li/a/@href').extract_first()

        yield item

    @staticmethod
    def random_cookie():
        """Return random cookie"""

        args = (uuid.uuid4(),) * 5
        cookie = '_ga=GA1.2.283417006.1528771266; user_trace_token={}; LGUID={}; _gid=GA1.2.1726150264.1537924083; ' \
                 'index_location_city=%E5%85%A8%E5%9B%BD; _qddaz=QD.iur0qw.llikm4.jmiq6c57; sajssdk_2015_cross_new_user=1;' \
                 ' sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221661885e6b81da-016893c9127d5e-8383268-' \
                 '1049088-1661885e6b971%22%2C%22%24device_id%22%3A%221661885e6b81da-016893c9127d5e-8383268-' \
                 '1049088-1661885e6b971%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9' \
                 'B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_referrer%22%3A%22%22%2C%22%24latest_referrer_' \
                 'host%22%3A%22%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%' \
                 'B4%E6%8E%A5%E6%89%93%E5%BC%80%22%7D%7D; JSESSIONID={}; _gat=1; Hm_lvt_4233e74dff0ae5bd0a3d81c6ccf756e6=' \
                 '1537924086,1537939245,1538009720,1538040806; Hm_lpvt_4233e74dff0ae5bd0a3d81c6ccf756e6=1538040806; LGSID={}; ' \
                 'PRE_UTM=; PRE_HOST=; PRE_SITE=; PRE_LAND=https%3A%2F%2Fwww.lagou.com; LGRID={}'.format(*args)
        return cookie
