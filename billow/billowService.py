from . import asg
from . import dns
from . import elb
from . import sec
from . import vpc
import boto
import datetime
import pprint
import billow
from .billowGroup import billowGroup


class billowService(object):

    """
    a large undulating mass of cloud services
    """

    def __init__(self, service, groups=[], region='us-east-1', environ=None,
                 parent=None):
        self.service = service
        self.environ = environ
        self.__groups = groups
        self.__region = region
        self.parent = parent
        self.__balancers = list()

        self.rawsgroups = None

        # service-env:region overrides passed in region
        if ':' in service:
            self.__region = service.split(':')[1]
            self.service = service.split(':')[0]

        # Backends
        if self.parent:
            self.asg = self.parent.asg
            self.dns = self.parent.dns
            self.elb = self.parent.elb
            self.sec = self.parent.sec
            self.vpc = self.parent.vpc
        else:
            self.asg = asg.asg(self.region)
            self.dns = dns.dns(self.region)
            self.elb = elb.elb(self.region)
            self.sec = sec.sec(self.region)
            self.vpc = vpc.vpc(self.region)

        self.tagservice = 'service'

    def config(self):
        self.__config = dict()
        c = self.__config
        c['region'] = self.region
        c['service'] = self.service
        c['environ'] = self.environ
        if self.cluster:
            c['cluster'] = self.cluster

        c['groups'] = list()
        for g in self.groups:
            c['groups'].append(g.config())

        c['security'] = dict()
        c['security']['groups'] = list()
        for sg in self.security_groups:
            c['security']['groups'].append(self.sg_name(sg, request=True))
        c['security']['rules'] = self.security_rules

        self.__load_balancers()
        c['balancers'] = dict()
        for b in self.balancers:
            c['balancers'][str(b.name)] = b.config()

        return self.__config

    def info(self):
        self.__info = self.config()

        for b in self.balancers:
            self.__info['balancers'][str(b.name)] = b.info()

        self.__info['groups'] = list()
        for g in self.groups:
            self.__info['groups'].append(g.info())

        return self.__info

    def __repr__(self):
        return pprint.pformat(self.config())

    def __str__(self):
        """
        service-env:region
        """
        return '%s-%s:%s' % (self.service, self.environ, self.region)

    def __unicode__(self):
        """
        service-env:region
        """
        return '%s-%s:%s' % (self.service, self.environ, self.region)

    def __eq__(self, other):
        """
        Match strings against 4 forms of service name:
        1. service-environ:region
        2. service-environ
        3. service:region
        4. service
        """
        if isinstance(other, str) or isinstance(other, unicode):
            if "%s-%s:%s" % (self.service, self.environ, self.region) == other:
                return True
            elif "%s-%s" % (self.service, self.environ) == other:
                return True
            elif "%s:%s" % (self.service, self.region) == other:
                return True
            else:
                return self.service == other
        return self.service == other.service and \
            self.environ == other.environ and \
            self.region == other.region

    def __load(self):
        self.__load_groups()

        # preserve update time for future caching decisions
        self.update_time = datetime.datetime.utcnow()

    def __load_groups(self, refresh=False):
        if self.__groups or not refresh:
            return

        groupnames = list()
        groups = list()
        baseservice = None

        # find all groups with service=(self)
        tags = self.asg.list_tags(tag=self.tagservice, value=self.service)
        for t in tags:
            groupnames.append(t.resource_id)
        asgs = self.asg.get_groups(groupnames)

        # retrieve all autoscale groups, push in data to save round trips
        for a in asgs:
            g = billowGroup(a.name, region=self.region, parent=self)
            g.push(a)
            groups.append(g)

        # undefined environment - simply select the first seen
        if not self.environ:
            for g in groups:
                self.environ = g.environ
                print "XXX set environ %s" % self.environ
                break

        # prune any groups that do not match the environment
        for g in groups[:]:
            if g.environ != self.environ:
                print "XXX throw away environ %s" % g.environ
                groups.remove(g)

        self.__groups = groups

    def __load_sgroups(self, refresh=False):
        if not self.rawsgroups or refresh:
            self.rawsgroups = self.sec.get_groups(self.security_groups)

    def __load_balancers(self, refresh=False):
        if not self.__balancers or refresh:
            self.__balancers = list()
            for g in self.groups:
                for lb in g.load_balancers:
                    if lb not in self.__balancers:
                        b = billow.billowBalancer(lb, region=self.region,
                                parent=self)
                        self.__balancers.append(b)

    def refresh(self):
        self.__load()
        self.__load_groups()
        self.__load_sgroups(refresh=True)
        self.__load_balancers(refresh=True)

    def add_group(self, groupname):
        """
        Add a group to the service by name
        """
        if not isinstance(groupname, basestring):
            raise TypeError
        if groupname not in self.groups:
            self.__groups.append(
                    billowGroup(groupname, region=self.region, parent=self)
                    )

    @property
    def region(self):
        if self.parent:
            return self.parent.region
        else:
            return self.__region

    @property
    def cluster(self):
        """
        return a common cluster name if all groups have the same cluster,
        otherwise None
        """
        cluster = None
        for g in self.groups:
            if not cluster:
                cluster = g.cluster
            if cluster != g.cluster:
                return None
        return cluster

    @property
    def ami(self):
        """
        return a common AMI name if all groups have the same AMI,
        otherwise None
        """
        ami = None
        for g in self.groups:
            if not ami:
                ami = g.ami
            if ami != g.ami:
                return None
        return ami

    @property
    def security_groups(self):
        self.__load_balancers()
        sgroups = list()
        for g in self.groups:
            sgroups.extend(x for x in g.security_groups if x not in sgroups)
        for b in self.balancers:
            sgroups.extend(x for x in b.security_groups if x not in sgroups)
        return sgroups

    def sg_name(self, sgid, request=False):
        self.__load_sgroups()
        for sg in self.rawsgroups:
            if sg.id == sgid:
                return str(sg.name)
        if request:
            sg = self.sec.get_groups(sgid)
            if sg:
                self.rawsgroups.append(sg[0])
                return str(sg[0].name)
        return str(sgid)

    @property
    def security_rules(self):
        self.__load_sgroups()
        srules = dict()
        for sg in self.rawsgroups:
            if sg.id not in self.security_groups:
                continue
            sg_name = self.sg_name(sg.id)
            if sg_name not in srules:
                srules[sg_name] = list()
            for sr in sg.rules:
                rule = dict()
                rule['from_port'] = sr.from_port
                if sr.grants:
                    for grant in sr.grants:
                        if grant.cidr_ip:
                            rule['cidr'] = grant.cidr_ip
                        if grant.group_id:
                            rule['group'] = self.sg_name(grant.group_id,
                                                         request=True)
                rule['ip_protocol'] = sr.ip_protocol
                rule['to_port'] = sr.to_port
                srules[sg_name].append(rule)
        return srules

    @property
    def balancers(self):
        self.__load_balancers()
        return self.__balancers

    @property
    def groups(self):
        self.__load_groups()
        return self.__groups

    @property
    def load_balancers(self):
        elbs = list()
        for b in self.balancers:
            elbs.append(b.name)
        return elbs

    def get_instance(self, instance):
        for g in self.groups:
            i = g.get_instance(instance)
            if i:
                return i
        return None
