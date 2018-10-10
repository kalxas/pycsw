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

    # def dataset(self):
    #     """
    #     Stub to mock a pycsw dataset object for Transactions
    #     """
    #     return type('Service', (object,), {})

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
        results = self._run_es_query(query)
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
        query = self.filter
        if constraint:
            query = '{}/{}'.format(constraint)
        return query

    def _run_es_query(self, query):

        try:
            url = "{}/search?index=md_index_1".format(query)
            response = requests.get(url=url)
        except requests.exceptions.ConnectionError as e:
            LOGGER.error('ConnectError connecting to Elastic search backend: {}'.format(e))
            return [0, []]
        except Exception as e:
            LOGGER.error('Elastic search backend error: {}'.format(e))
            return 'Elastic search backend error: {}'.format(e)

        if response.status_code != 200:
            raise RuntimeError('Request failed with return code: %s' % (
                response.status_code))

        try:
            json_dict = json.loads(response.text)
        except Exception as e:
            raise RuntimeError('response is not valid json: {}'.format(e))

        if not json_dict.get('success', False):
            raise RuntimeError('response success is false')
        if not json_dict.get('results', False):
            raise RuntimeError('response has no results')
        results = self.transpose_records(json_dict['results'])
        return [str(len(results)), results]

    def elastic_available(self, url):
        try:
            response = requests.get(url="{}/read".format(url))
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

        result = MAPPING
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

        # lstCreators = record.get('creators', False)
        # if lstCreators:
        #     for crt in lstCreators:
        #         creatorName = crt['creatorName']
        #         if creatorName:
        #             child = ET.SubElement(oai_dc, 'dc:creator')
        #             child.text = creatorName

        # lstSubjects = record['subjects']
        # if lstSubjects:
        #     for sbj in lstSubjects:
        #         subject = sbj['subject']
        #         if subject:
        #             # Add all subjects
        #             child = ET.SubElement(oai_dc, 'dc:subject')
        #             child.text = subject

        # dc_date = get_dc_date(record)
        # if dc_date is not None:
        #     child = ET.SubElement(oai_dc, 'dc:date')
        #     child.text = dc_date

        # if record.get('resourceType', '') != '':
        #     child = ET.SubElement(oai_dc, 'dc:type', {
        #         'xsi.type': "dct:DCMIType"})
        #     child.text = record.get('resourceType')

        # # # Not sure where to get the type URI
        # # child = ET.SubElement(oai_dc, 'dc:identifier', {
        # #     'xsi.type': "dct:URI"})
        # # child.text = record['identifier']['identifier']

        # lstRights = record.get('rights', [])
        # if len(lstRights):
        #     for rgt in lstRights:
        #         child = ET.SubElement(oai_dc, 'dc:rights')
        #         child.text = rgt['rights']

        # lstDescriptions = record['description']
        # if lstDescriptions:
        #     # descriptionType is empty but shows Abstract on the real xml
        #     for dsp in lstDescriptions:
        #         description = ET.SubElement(oai_dc, 'dc:description')
        #         description.text = dsp['description']

        print(result)
        dataset = type('', (object,), result)()
        return dataset


MAPPING = {
    # 'pycsw:Identifier': '',
    # # CSW typename (e.g. csw:Record, md:MD_Metadata)
    # 'pycsw:Typename': 'typename',
    # # schema namespace, i.e. http://www.isotc211.org/2005/gmd
    # 'pycsw:Schema': 'schema',
    # # origin of resource, either 'local', or URL to web service
    # 'pycsw:MdSource': 'mdsource',
    # # date of insertion
    # 'pycsw:InsertDate': 'insert_date',  # date of insertion
    # # raw XML metadata
    # 'pycsw:XML': 'xml',
    # # bag of metadata element and attributes ONLY, no XML tages
    # 'pycsw:AnyText': 'anytext',
    # 'pycsw:Language': 'language',
    # 'pycsw:Title': 'title',
    # 'pycsw:Abstract': 'abstract',
    # 'pycsw:Keywords': 'keywords',
    # 'pycsw:KeywordType': 'keywordstype',
    # 'pycsw:Format': 'format',
    # 'pycsw:Source': 'source',
    # 'pycsw:Date': 'date',
    # 'pycsw:Modified': 'date_modified',
    # 'pycsw:Type': 'type',
    # geometry, specified in OGC WKT
    'wkt_geometry': None,
    # 'pycsw:CRS': 'crs',
    # 'pycsw:AlternateTitle': 'title_alternate',
    # 'pycsw:RevisionDate': 'date_revision',
    # 'pycsw:CreationDate': 'date_creation',
    # 'pycsw:PublicationDate': 'date_publication',
    # 'pycsw:OrganizationName': 'organization',
    # 'pycsw:SecurityConstraints': 'securityconstraints',
    # 'pycsw:ParentIdentifier': 'parentidentifier',
    # 'pycsw:TopicCategory': 'topicategory',
    # 'pycsw:ResourceLanguage': 'resourcelanguage',
    # 'pycsw:GeographicDescriptionCode': 'geodescode',
    # 'pycsw:Denominator': 'denominator',
    # 'pycsw:DistanceValue': 'distancevalue',
    # 'pycsw:DistanceUOM': 'distanceuom',
    # 'pycsw:TempExtent_begin': 'time_begin',
    # 'pycsw:TempExtent_end': 'time_end',
    # 'pycsw:ServiceType': 'servicetype',
    # 'pycsw:ServiceTypeVersion': 'servicetypeversion',
    # 'pycsw:Operation': 'operation',
    # 'pycsw:CouplingType': 'couplingtype',
    # 'pycsw:OperatesOn': 'operateson',
    # 'pycsw:OperatesOnIdentifier': 'operatesonidentifier',
    # 'pycsw:OperatesOnName': 'operatesoname',
    # 'pycsw:Degree': 'degree',
    # 'pycsw:AccessConstraints': 'accessconstraints',
    # 'pycsw:OtherConstraints': 'otherconstraints',
    # 'pycsw:Classification': 'classification',
    # 'pycsw:ConditionApplyingToAccessAndUse': 'conditionapplyingtoaccessanduse',
    # 'pycsw:Lineage': 'lineage',
    # 'pycsw:ResponsiblePartyRole': 'responsiblepartyrole',
    # 'pycsw:SpecificationTitle': 'specificationtitle',
    # 'pycsw:SpecificationDate': 'specificationdate',
    # 'pycsw:SpecificationDateType': 'specificationdatetype',
    # 'pycsw:Creator': 'creator',
    # 'pycsw:Publisher': 'publisher',
    # 'pycsw:Contributor': 'contributor',
    # 'pycsw:Relation': 'relation',
    # # links: format "name,description,protocol,url[^,,,[^,,,]]"
    # 'pycsw:Links': 'links',
}
