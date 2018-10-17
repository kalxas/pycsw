# -*- coding: iso-8859-15 -*-
# =================================================================
#
# Authors: Mike Metcalfe <mikejmets@gmail.com>
# Credit: Base on the pycsw hypermap plugin that was
#         written by Tom Kralidis <tomkralidis@gmail.com>
#         https://github.com/cga-harvard/Hypermap-Registry
#
# Copyright (c) 2015 Mike Metcalfe
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

import logging
import json
import requests
# from pycsw.core import util

LOGGER = logging.getLogger(__name__)


class ElasticSearchRepository(object):
    """
    Class to interact with underlying repository
    """
    def __init__(self, context, repo_filter=None):
        """
        Initialize repository
        """

        self.context = context
        self.filter = repo_filter
        self.fts = False
        self.label = 'ElasticSearch'
        self.local_ingest = True

        self.dbtype = 'elasticsearch'

        # generate core queryables db and obj bindings
        self.queryables = {}

        for tname in self.context.model['typenames']:
            for qname in self.context.model['typenames'][tname]['queryables']:
                self.queryables[qname] = {}
                items = self.context.model['typenames'][tname]['queryables'][qname].items()

                for qkey, qvalue in items:
                    self.queryables[qname][qkey] = qvalue

        # flatten all queryables
        # TODO smarter way of doing this
        self.queryables['_all'] = {}
        for qbl in self.queryables:
            self.queryables['_all'].update(self.queryables[qbl])
        self.queryables['_all'].update(self.context.md_core_model['mappings'])

        # Check if elastic service is up
        if not self.elastic_available(self.filter):
            raise Exception('ElasticSearch backend not available')

    def query_ids(self, ids):
        """
        Query by list of identifiers
        """

        results = self._get_repo_filter(Layer.objects).filter(uuid__in=ids).all()

        if len(results) == 0:  # try services
            results = self._get_repo_filter(Service.objects).filter(uuid__in=ids).all()

        return results

    def query_domain(self, domain, typenames, domainquerytype='list', count=False):
        """
        Query by property domain values
        """

        # objects = self._get_repo_filter(Layer.objects)

        # if domainquerytype == 'range':
        #     return [tuple(objects.aggregate(Min(domain), Max(domain)).values())]
        # else:
        #     if count:
        #         return [(d[domain], d['%s__count' % domain])
        #                 for d in objects.values(domain).annotate(Count(domain))]
        #     else:
        #         return objects.values_list(domain).distinct()

    def query_source(self, source):
        """
        Query by source
        """
        return self._get_repo_filter(Layer.objects).filter(url=source)

    def query(self, constraint, sortby=None, typenames=None, maxrecords=10, startposition=0):
        """
        Query records from underlying repository
        """

        # run the raw query and get total
        # we want to exclude layers which are not valid, as it is done in the search engine
        query = self._get_repo_filter(constraint)
        print(str(query))
        results = self._run_es_query(self.filter, query)
        print(str(results))
        return results

        # total = query.count()
        # # apply sorting, limit and offset
        # if sortby is not None:
        #     if 'spatial' in sortby and sortby['spatial']:  # spatial sort
        #         desc = False
        #         if sortby['order'] == 'DESC':
        #             desc = True
        #         query = query.all()
        #         return [str(total),
        #                 sorted(query,
        #                        key=lambda x: float(util.get_geometry_area(getattr(x, sortby['propertyname']))),
        #                        reverse=desc,
        #                        )[startposition:startposition + int(maxrecords)]]
        #     else:
        #         if sortby['order'] == 'DESC':
        #             pname = '-%s' % sortby['propertyname']
        #         else:
        #             pname = sortby['propertyname']
        #         return [str(total),
        #                 query.order_by(pname)[startposition:startposition + int(maxrecords)]]
        # else:  # no sort
        #     return [str(total), query.all()[startposition:startposition + int(maxrecords)]]

    def _get_repo_filter(self, constraint):
        """
        Apply repository wide side filter / mask query
        """
        query = {}
        if constraint:
            if constraint.get('type') == 'filter':
                field = None
                value = None
                where = constraint.get('where')
                where_lst = where.split(' ')
                if where_lst[0] == 'title':
                    field = 'metadata_json.titles.title'
                values = constraint.get('values')
                if len(values) > 0:
                    value = values[0]
                    value = value.replace('%', '')
                if field and value:
                    query = {field: value}

        return query

    def _run_es_query(self, base_url, params):

        try:
            params['index'] = 'md_index_1'
            print(str(params))
            response = requests.post(url=base_url, params=params)
        except requests.exceptions.ConnectionError as e:
            LOGGER.error('ConnectError connecting to Elastic search backend: {}'.format(e))
            return ['0', []]
        except Exception as e:
            LOGGER.error('Elastic search backend error: {}'.format(e))
            return ['0', []]

        if response.status_code != 200:
            LOGGER.error('Request failed with return code: %s' % (
                response.status_code))
            return ['0', []]

        try:
            json_dict = json.loads(response.text)
        except Exception as e:
            LOGGER.error('Response is not valid json: {}'.format(e))
            return ['0', []]

        if not json_dict.get('success', False):
            LOGGER.error('Backend request was unsuccess')
            return ['0', []]
        if not json_dict.get('results', False):
            LOGGER.error('Backend returned no results')
            return ['0', []]

        results = self.transpose_records(json_dict['results'])
        return [str(len(results)), results]

    def elastic_available(self, url):
        try:
            response = requests.get(url="{}".format(url))
        except Exception as e:
            LOGGER.error('ConnectError connecting to ElasticSearch backend: {}'.format(e))
            return False
        if response.status_code != 200:
            LOGGER.error('Connecting to ElasticSearch backend failed with return code: %s' % (response.status_code))
            return False
        return True

    def transpose_records(self, records):
        results = []
        for record in records:
            try:
                results.append(
                    self.transpose_a_record(record['metadata_json']))
            except AttributeError as e:
                print('AttributeError: {}'.format(e))
                raise e

        return results

    def transpose_a_record(self, record):

        result = {
            'wkt_geometry': None,
        }
        if record.get('identifier', ''):
            result['identifier'] = record['identifier']['identifier']

        if record.get('resourceType'):
            result['type'] = record.get('resourceType')

        lstTitles = record.get('titles', '')
        if lstTitles:
            primary_is_set = False
            for ttl in lstTitles:
                title = ttl['title']
                if title:
                    if not primary_is_set:
                        # Use the first title
                        result['title'] = title
                        primary_is_set = True
                    elif not result.get('alternateTitle'):
                        result['alternateTitle'] = title
                        break

        publisher = record.get('publisher', False)
        if publisher:
            result['publisher'] = publisher

        lstContributors = record.get('contributors', False)
        if lstContributors:
            for cbt in lstContributors:
                contributorName = cbt['contributorName']
                if contributorName:
                    result['contributor'] = contributorName
                    break

        lstCreators = record.get('creators', False)
        if lstCreators:
            # creators = []
            # for crt in lstCreators:
            #     creatorName = crt['creatorName']
            #     if creatorName:
            #         creators.append(creatorName)
            # result['creator'] = ','.join(creators)
            for crt in lstCreators:
                creatorName = crt['creatorName']
                if creatorName:
                    result['creator'] = creatorName
                    break

        lstSubjects = record['subjects']
        if lstSubjects:
            keywords = []
            for sbj in lstSubjects:
                subject = sbj['subject']
                if subject:
                    # Add all subjects
                    keywords.append(subject)
            result['keywords'] = ','.join(keywords)

        dc_date = get_dc_date(record)
        if dc_date:
            result['date'] = dc_date

        lstRights = record.get('rights', [])
        if len(lstRights):
            rights = []
            for rgt in lstRights:
                rights.append(rgt['rights'])
            result['accessconstraints'] = ','.join(rights)

        lstDescriptions = record['description']
        if lstDescriptions:
            # descriptionType is empty but shows Abstract on the real xml
            for desc in lstDescriptions:
                if desc.get('descriptionType', '') in ['', 'abstract']:
                    result['abstract'] = desc['description']
                    break

        # TODO OUSTANDING FIELDS
        # boundingbox
        # modified
        # source
        # language
        # format
        # references

        print(result)
        dataset = type('', (object,), result)()
        return dataset


def get_dc_date(record):
    dates = record.get('dates', [])
    dc_date = None
    for adate in dates:
        if adate.get('dateType') and \
           adate.get('dateType') == 'Submitted' and \
           adate.get('date'):
            dc_date = adate.get('date')
            break

    if dc_date is None:
        year = record.get('publicationYear')
        if year:
            dc_date = year

    return dc_date
