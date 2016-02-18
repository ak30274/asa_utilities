#!/usr/bin/python3

# ./ACL_check.py -f <input_file> -s <subnet>
# This script inputs a cisco config file and a subnet or IP address, and outputs any relevant
# objects pertaining to access lists.
# brf2010@med.cornell.edu

from ciscoconfparse import CiscoConfParse, IOSCfgLine
from ciscoconfparse.ccp_util import IPv4Obj
from ASA_ACL import ASA_ACL
import re
import sys
import pickle
import argparse


# regular expressions used throughout
RE_OBJECT_NETWORK = re.compile('^object network (\S+)$')
RE_OBJECT_GROUP = re.compile('^object-group network (\S+)$')
RE_HOST = re.compile('^ host\s(\S+)$')
RE_SUBNET = re.compile('^ subnet ([\S ]+)$')
RE_NETWORK_OBJECT_HOST = re.compile('^ network-object host (\S+)$')
RE_NETWORK_OBJECT_OBJECT = re.compile('^ network-object object (\S+)$')
RE_BARE_ACL_HOST = re.compile('host ((?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))')
RE_BARE_SUBNET = re.compile('(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?) (?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)')



# parse arguments and determine a course of action
parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter,
	description="Check for relevant ACLs in a cisco config",
	epilog=
"""Examples:\n\
	Check an IP against a cisco config file: ACL_check.py -f config -i 1.2.3.4\n\
	Generate a pickle file for faster lookups: ACL_check.py -f config -o pickle\n\
	Check IP against pickle file: ACL_check.py -p pickle -i 1.2.3.4\n\
	Check source IP only, from the Outside-IN access-list, against a config file: ACL_check.py -s 8.8.8.8 -a Outside-IN -p pickle
It is strongly advised to generate and use a pickle file to speed things up.""")


# group IP arguments together
ip_groups = parser.add_argument_group("IP address specification")
ip_groups.add_argument('-i', help="subnet/IP to check", dest="ip")
ip_groups.add_argument('-s', help="source subnet/IP to check", dest="source")
ip_groups.add_argument('-d', help="destination subnet/IP to check", dest="dest")
parser.add_argument('-a', help="access-list name to check. if omitted, assumes all lists", dest="acl_name")
# pickle and plaintext inputs are mutually exclusive
input_group = parser.add_mutually_exclusive_group()
input_group.add_argument('-f', help="input config file", dest="in_file")
input_group.add_argument('-p', help="input pickle file", dest="pickle_file")
parser.add_argument('-o', help="output pickle file. used in conjunction with -f", dest="out_file")

parser.add_argument('--debug', help="debug", dest="debug", action="store_true")
args = parser.parse_args()

debug=args.debug


# check for conflicting arguments and raise errors as necessary
if args.out_file and (args.ip or args.source or args.dest):
	parser.error("out_file conflicts with -i, -s, and -d")
	sys.exit()
if args.pickle_file and args.out_file:
	parser.error("-p is only compatible with -f")
	sys.exit()
if args.ip and (args.source or args.dest):
	parser.error("-s and -d cannot be used in conjunction with -i")
	sys.exit()
if not (args.ip or args.source or args.dest or args.out_file):
	parser.error("One of [-i | -s | -d] or -o must be given.")
	sys.exit()
if not (args.in_file or args.pickle_file):
	parser.error("One of -f or -p is necessary")
	sys.exit()


# are we generating a pickle file from an input?
if args.out_file and args.in_file:
	print("Generating pickle file. This can take some time with very large files. Try getting some coffee.")
	fh = open(args.out_file, 'wb')
	config = CiscoConfParse(args.in_file)
	pickle.dump(config, fh)
	print("Done.")
	sys.exit()


# if we made it this far, we have an input! try to cast our inputs to things and see if shit explodes!
subnet = None
source = None
dest = None

if args.ip:
	# try to cast to IPv4Obj for syntax checking
	try:
		subnet = IPv4Obj(args.ip)
	except:
		print("Invalid subnet/IP")
		if debug: print(args.ip)
		sys.exit()
if args.source:
	try:
		source = IPv4Obj(args.source)
	except:
		print("Invalid subnet/IP")
		if debug: print(args.source)
		sys.exit()
if args.dest:
	try:
		dest = IPv4Obj(args.dest)
	except:
		print("Invalid subnet/IP")
		if debug: print(args.dest)
		sys.exit()

if debug: print(subnet)
if debug: print(source)
if debug: print(dest)


# are we loading from a pickle?
if args.pickle_file:
	if debug: print("loading %s as pickle file" %(args.pickle_file))
	config = pickle.load(open(args.pickle_file, 'rb'))
# if not, load in a file
elif args.in_file:
	if debug: print("loading %s as plaintext file" %(args.in_file))
	config = CiscoConfParse(args.in_file)




# functions and stuff

def is_substring_of_obj_list(obj_name, matched_objects):
	# helper function for checking substrings in an object list
	for obj in matched_objects:
		if obj_name in obj.text:
			return True
	return False

def match_network_objects(subnet, network_objects):
	# takes in an IPv4Obj and a list of network_objects. returns a list of network_objects
	# that match based on if the network_object address(es) are in the subnet or if the subnet
	# is in the network_object
	if debug: print('matching network objects with specified subnet')
	matched_objects = []
	for obj in network_objects:
		#print(obj)
		#print(obj.children)
		for child in obj.children:
			# match any statically defined hosts
			ip_str = child.re_match(RE_HOST, default=None)
			if not ip_str:
				# try to match subnet definitions
				ip_str = child.re_match(RE_SUBNET, default=None)

			if ip_str:
				# if we found an IP address, convert to IPv4Obj and check if it belongs
				# to the subnet we want, and vice-versa
				addr = IPv4Obj(ip_str)
				if addr in subnet:
					matched_objects.append(obj)
					break
				elif subnet in addr:
					matched_objects.append(obj)
					break
			# TODO: match any statically defined subnets
	return matched_objects

def match_network_object_groups(subnet, object_groups, matched_objects):
	# takes in an IPv4Obj, a list of object_groups, and a list of network_objects that were previously matched.
	# iterates through the object_groups and returns a list of all object groups that matched either the subnet
	# or one of the objects in matched_objects
	matched_groups = []
	for group in object_groups:
		# accumulate children
		children = []
		for child in group.children:
			# match any previously discovered network objects
			network_object = child.re_match(RE_NETWORK_OBJECT_OBJECT, default=None)
			# match any statically defined hosts
			if not network_object:
				ip_str = child.re_match(RE_NETWORK_OBJECT_HOST, default=None)

			if network_object:
				if is_substring_of_obj_list(network_object, matched_objects):
					children.append(child)
					# break
			elif ip_str:
				addr = IPv4Obj(ip_str)
				if addr in subnet:
					children.append(child)
					# break

		# if there were children for this group, make a copy of all of them and
		# append them to matched_groups. this is to limit the noise that is output by
		# the group portion of the output section below; we only care why a given
		# object group was selected, not about all of its contents.
		if children:
			# create new parent that is the same as the one we have but without children
			parent = IOSCfgLine(group.text)
			# and give it children that are pertinent to our query
			for child in children:
				parent.add_child(child)
			# then append it to our matched groups
			matched_groups.append(parent)
	return matched_groups



# get all network objects
if debug: print('finding network objects')
net_objs = config.find_objects(RE_OBJECT_NETWORK)

# match ips, sources, and destinations against network objects
if subnet:
	matched_objects = match_network_objects(subnet, net_objs)
if source:
	source_matched_objects = match_network_objects(source, net_objs)
if dest:
	dest_matched_objects = match_network_objects(dest, net_objs)



# get all object groups
if debug: print('finding object groups')
object_groups = config.find_objects(RE_OBJECT_GROUP)

# match ips, sources, and destinations against object groups
if subnet:
	matched_groups = match_network_object_groups(subnet, object_groups, matched_objects)
if source:
	source_matched_groups = match_network_object_groups(source, object_groups, source_matched_objects)
if dest:
	dest_matched_groups = match_network_object_groups(dest, object_groups, dest_matched_groups)


# get access list items
if debug: print("extracting access-list")
ACL = config.find_objects("^access-list ")
ACL_matches = []
for line in ACL:
	# check network objects
	for obj in matched_objects:
		obj_name = obj.re_match(RE_OBJECT_NETWORK)
		if obj_name in line.text:
			ACL_matches.append(line)
			break
	# check object groups
	for obj_group in matched_groups:
		obj_name = obj_group.re_match(RE_OBJECT_GROUP)
		if obj_name in line.text:
			ACL_matches.append(line)
			break
	# check bare IP addresses
	IPs = RE_BARE_ACL_HOST.findall(line.text)
	for IP in IPs:
		if IPv4Obj(IP) in subnet:
			ACL_matches.append(line)
			break
	# check bare subnets
	IPs = RE_BARE_SUBNET.findall(line.text)
	# if IPs:
	# 	print(line.text)
	for IP in IPs:
		try:
			if IPv4Obj(IP) in subnet:
				ACL_matches.append(line)
				break
		except:
			pass

print("Matched network objects")
for obj in matched_objects:
	print(obj.text)
	for child in obj.children:
		print(child.text)

print("\nMatched object groups")
for obj in matched_groups:
	print(obj.text)
	for child in obj.children:
		print(child.text)

print("\nMatched ACLs")
for line in ACL_matches:
	print(line.text)
