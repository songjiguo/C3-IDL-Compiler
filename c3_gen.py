#------------------------------------------------------------------------------
# pycparser: c-to-c.py
#
# Example of using pycparser.c_generator, serving as a simplistic translator
# from C to AST and back to C.
#
# Copyright (C) 2008-2015, Eli Bendersky
# License: BSD
#------------------------------------------------------------------------------
from __future__ import print_function
from pycparser import parse_file, preprocess_file
from pycparser import c_parser, c_ast, c_generator, c_parser, c_generator
from pprint import pprint
import keywords, sys, os, re, time
from igraph import *

# use this to manage condition evaluation
from pyparsing import infixNotation, opAssoc, Keyword, Word, alphas  # @UnresolvedImport

import c3_parser

using_main = 1
max_params = 4  # up to 4 parameters in Composite
write_to_file = 1  # simply for testing only, no write files

# transparent to the user (used internally, so no need to dynamically change)
desc_track_server_id = "int IDL_server_id"
desc_track_fault_cnt = "unsigned long long fault_cnt"
desc_track_state = "unsigned int state"
desc_track_next_state = "unsigned int next_state"
desc_track_subtree_parent = "unsigned int is_parent"

root_function = ""
creation_function = ""
final_id = ""
final_id_type = ""
final_parent_id = ""
final_parent_id_type = ""
final_parent_component = ""

marshalling_flag = False

class MyCode():
    def __init__(self):
        self.ifcode = {}
        
    def add_interface(self, if_name):
        self.ifcode[if_name] = InterfaceCode(if_name)

class InterfaceCode(object):
    def __init__(self, interface_name):
        self.blocks = {}
        self.name   = interface_name
    
    def add_block(self, block_name):
        self.blocks[block_name] = BlockCode(block_name)

class BlockCode(object):
    def __init__(self, block_name):
        self.rules = []
        self.name   = block_name
        self.block_code = ""
        
    def gen_code(self, arg1, *args):   # pass the conditions in
        #print ("Python does not support function overloading")
        #self.set_name(arg1)
        
        if args:
            #for item in args:
            #    print (item)
            self.block_code = "hello world" 
        else:
            print (arg1)
            
    def set_name(self, block_name):
        name = block_name

    def show_code(self):
        print (self.block_code)

# define classes to be built at parse time, as each matching
# expression type is parsed
class BoolOperand(object):
    def __init__(self,t):
        self.label = t[0]
        self.value = eval(t[0])
    def __bool__(self):
        return self.value
    def __str__(self):
        return self.label
    __repr__ = __str__
    __nonzero__ = __bool__

class BoolBinOp(object):
    def __init__(self,t):
        self.args = t[0][0::2]
    def __str__(self):
        sep = " %s " % self.reprsymbol
        return "(" + sep.join(map(str,self.args)) + ")"
    def __bool__(self):
        return self.evalop(bool(a) for a in self.args)
    __nonzero__ = __bool__
    __repr__ = __str__

class BoolAnd(BoolBinOp):
    reprsymbol = '&'
    evalop = all

class BoolOr(BoolBinOp):
    reprsymbol = '|'
    evalop = any

class BoolNot(object):
    def __init__(self,t):
        self.arg = t[0][1]
    def __bool__(self):
        v = bool(self.arg)
        return not v
    def __str__(self):
        return "~" + str(self.arg)
    __repr__ = __str__
    __nonzero__ = __bool__

TRUE = Keyword("True")
FALSE = Keyword("False")
boolOperand = TRUE | FALSE | Word(alphas,max=1)
boolOperand.setParseAction(BoolOperand)

# define expression, based on expression operand and
# list of operations in precedence order
boolExpr = infixNotation( boolOperand,
    [
    ("not", 1, opAssoc.RIGHT, BoolNot),
    ("and", 2, opAssoc.LEFT,  BoolAnd),
    ("or",  2, opAssoc.LEFT,  BoolOr),
    ])

# visible to the programmer
desc_close_self_only   = False
desc_close_subtree     = False
desc_dep_create_none   = False
desc_dep_create_diff   = False
desc_dep_create_same   = False
desc_dep_close_removal = False
desc_dep_close_keep    = False
desc_global            = False
desc_block             = False
resc_has_data          = False
desc_has_data          = False
creation               = False
transition             = False
terminal               = False
server_block           = False
server_wakeup          = False

# invisible to the programmer
always_appear          = True  # alwasy appear
marshalling            = False # no marshalling by default
create_new_id          = True  # majority create APIs return new id, except mem_get_page and pte
temporal               = False
#===============================================================================
#
#  EXTRACT THE INFO AND CONSTRUCT THE CODE BLOCKS
#
#===============================================================================
#===============================================================================
#  block is in the form of (predicate, code, blk name)
#  gdescp is in the form of ['desc_close_self_only', 'desc_global_global', ...]
#  fdescp is in the form of [function name, normalPara, sm_state, idlRet, idlPara]
#===============================================================================
def init_cond_table(gdescp, fdescp):
    global desc_close_self_only, desc_close_subtree, desc_dep_create_none, desc_dep_create_diff, desc_block;
    global desc_dep_create_same, desc_dep_close_removal, desc_dep_close_keep, desc_global, marshalling
    global server_wakeup, server_block, resc_has_data, desc_has_data, creation,transition, terminal, temporal
    if (1):
        desc_close_self_only    = "desc_close_self_only"   in gdescp
        desc_close_subtree      = "desc_close_subtree"     in gdescp
        desc_dep_create_none    = "desc_dep_create_none"   in gdescp
        desc_dep_create_diff    = "desc_dep_create_diff"   in gdescp
        desc_dep_create_same    = "desc_dep_create_same"   in gdescp
        desc_dep_close_removal  = "desc_dep_close_removal" in gdescp
        desc_dep_close_keep     = "desc_dep_close_keep"    in gdescp
        desc_global             = "desc_global"            in gdescp
        desc_block              = "desc_block"             in gdescp
        resc_has_data           = "resc_has_data"          in gdescp
        desc_has_data           = "desc_has_data"          in gdescp
    
    if (fdescp):
        creation        = "creation"        in fdescp[2]
        transition      = "transition"      in fdescp[2]
        terminal        = "terminal"        in fdescp[2]
        temporal        = "temporal"        in fdescp[2]
        server_block    = "server_block"    in fdescp[5]  # see the generate_description
        server_wakeup   = "server_wakeup"   in fdescp[5]
    if (gdescp == "marshalling" and fdescp is None):
        marshalling = True
   
def condition_eval(block, (gdescp, fdescp)):
    IFCode = ""
    IFBlkName = ""
    
    init_cond_table(gdescp, fdescp)
    for blk in block.list:
        if (eval(blk[0])):      # blk[0] is the list of predicates
            IFCode = blk[1]     # blk[1] is the block code
            IFBlkName = blk[2]  # blk[2] is the block name
                
    #===========================================================================
    # #pprint(gdescp)
    # #pprint(fdescp)
    # #print(desc_close_self_only & desc_close_subtree)
    # 
    # #list_descp = list(traverse(gdescp)) + list(traverse(fdescp))
    # #find_any = False
    # #print(list(traverse(gdescp)))
    # #print(block.list)
    # # blk[0] is the predicate
    # for blk in block.list:
    #     if (eval(blk[0])):      # blk[0] is the list of predicates
    #         IFCode = blk[1]     # blk[1] is the block code
    #         IFBlkName = blk[2]  # blk[2] is the block name
    #         #print(IFBlkName)
    #         #print(IFCode)
    #===========================================================================
        
#===============================================================================
#         list_blks = []
#         __list_blks = list(traverse(blk[0]))
#         for item in __list_blks:
#             list_blks = list_blks + item.split("&") 
#         match = 0;
#         #print(list_blks)
#         for pred in list_blks:
#             #print(pred)
#             for desc in list_descp:
#                 if (desc and desc in pred):
#                     match = match + 1;
# 
#         if (match == len(list_blks)):
#             IFCode = blk[1] + block.list[-1][1]   # last(pred, code) -- [-1][1] is for function pointer
#             IFBlkName = blk[2]
#             find_any = True
#             break;  # stop once we have found a match TODO: check the consistency
# 
#     if (find_any is False):
#         for blk in block.list:
#             if (blk[0][0] == "no match"):
#                 return (blk[0][0], blk[1])
#===============================================================================
    return (IFBlkName, IFCode)

def extrac_funcdecl_from_func(code):
    func_decl = code.lstrip().splitlines()[0]
    func_decl = func_decl[:func_decl.rfind("{")] + ";\n"
    return func_decl
        
def traverse(o, tree_types=(list, tuple)):
    if isinstance(o, tree_types):
        for value in o:
            for subvalue in traverse(value, tree_types):
                yield subvalue
    else:
        yield o

# this is to repalce for each function, not global
# fdesc[0] is the func name, fdesc[1] is the normal pars
# fdesc[4] is the IDL-ed pars  
def replace_params(result, fdesc, code, IFcode, subIFcode, param_list, paramdecl_list):
    name    = fdesc[0]

    if (param_list):
        code = code.replace("IDL_params", ', '.join(param_list))
        code = code.replace("IDL_pars_len", str(len(param_list)))
        code = code.replace("IDL_parsdecl", ', '.join(paramdecl_list))
        code = code.replace("IDL_fname", name)
    else: # these are for the function with void parameter list
        code = code.replace("IDL_params,", '')
        code = code.replace(", IDL_params", '')
        code = code.replace("IDL_params", '')
        code = code.replace(", IDL_pars_len", '')
        code = code.replace("IDL_pars_len,", '')
        code = code.replace("IDL_pars_len", '')
        code = code.replace(", IDL_parsdecl", '')
        code = code.replace("IDL_parsdecl,", '')
        code = code.replace("IDL_parsdecl", '')
        code = code.replace("IDL_fname", name)
    
    if (fdesc[2] != "creation"):
        server_id_param = subIFcode["parameters"]["params"]
        if ("desc_id" in IFcode["trackds"]):
            server_id_param = server_id_param.replace(IFcode["trackds"]["desc_id"][1], \
                                                      "desc->server_" + IFcode["trackds"]["desc_id"][1])
        code = code.replace("IDL_server_id_params", server_id_param)

    for tup in result.tuple:
        for func in tup.functions:
            if (fdesc[0] == func.info["funcname"]):
                code = code.replace("IDL_fntype", func.info["functype"])
    
    return code        

def generate_globalvas(result, IFcode):
    IFcode["s_stub.S"] = []
    if (keywords.service_name != "mem_mgr"):  # mm does not block
        keywords.get_lock_function(IFcode, keywords.service_name)

    global final_id, final_parent_id, final_parent_component, final_id_type, final_parent_id_type
    global create_new_id

    # set up the tracking strcuture
    IFcode["trackds"] = {"code":  IFcode["global_non_function"]["BLOCK_CLI_IF_TRACKING_STRUCT"]}
    code = IFcode["trackds"]["code"]
    IFcode["trackds"] = {"fields":[]}

    tmp = "\n" + code.split()[0] + " " + code.split()[1] + " { \n"
    for item in result.gvars["desc_data"]:
        tmp = tmp + "    " + " ".join(item) + ";\n"
        
    
    # transparent to the user
    tmp = tmp + "    " + desc_track_state + ";\n"  
    tmp = tmp + "    " + desc_track_next_state + ";\n"  
    tmp = tmp + "    " + desc_track_fault_cnt + ";"    
    
    if (desc_close_subtree):
        tmp = tmp + "    " + "\n\n"  
        tmp = tmp + "    "  + desc_track_subtree_parent + ";\n"  
        tmp = tmp + "    " + "struct IDL_desc_track *next, *prev" + ";\n"
        
    if (not desc_global and create_new_id):
        tmp = tmp + "    " + desc_track_server_id + ";\n"

    tmp = tmp + "\n};\n"  
    code = code.replace("struct IDL_desc_track\n", tmp) # only replace a line, not everywhere
    code = code.replace("struct IDL_desc_track", "struct desc_track") # only replace a line, not everywhere

    # all fields of desc_track (to replace in the function params)
    tmp = ""
    for item in result.gvars["desc_data"]:
        tmp = tmp + " ".join(item) + ", "
        IFcode["trackds"]["fields"].append(item[1])
    code = code.replace("IDL_desc_track_fields", tmp[:-2])  # -2 is to remove last ","
    # internal function files
    #code = r'''#include "cidl_gen.h"''' + "\n" + code 
    #pprint(result.gvars)
    
    if ("id" in result.gvars):
        IFcode["trackds"]["desc_id"] = result.gvars["id"]
    if ("parent id" in result.gvars):
        IFcode["trackds"]["desc_parent id"] = result.gvars["parent id"]
    if ("parent component" in result.gvars):
        IFcode["trackds"]["desc_parent component"] = result.gvars["parent component"]
    IFcode["trackds"]["code"] = code

    if ("desc_id" in IFcode["trackds"]):
        final_id_type = IFcode["trackds"]["desc_id"][0]
        final_id      = IFcode["trackds"]["desc_id"][1]
    if ("desc_parent id" in IFcode["trackds"]):
        final_parent_id_type = IFcode["trackds"]["desc_parent id"][0]
        final_parent_id      = IFcode["trackds"]["desc_parent id"][1]
    if ("desc_parent component" in IFcode["trackds"]):
        final_parent_component = IFcode["trackds"]["desc_parent component"][1]

    #print(IFcode["trackds"]["fields"])
    #print(result.gvars["desc_data"])
    #pprint(result.gvars)

def generate_gblocks(result, globalblocks, global_nonfun_blocks, IFDesc, IFcode):
    # the global blocks
    IFcode["internalfn_decl"] = ""
    IFcode["extern"] = "" 
    IFcode["mapping ds"] = ""
    IFcode["mapping fn"] = ""
    IFcode["desc_con"] = ""
    no_match_code_list = []
    
    if (globalblocks):
        __IFcode = {}
        for gblk in globalblocks:
            #print (gblk.list)
            name, code= condition_eval(gblk, (IFDesc[0], None))
            if (name and code):    # there should be any params, otherwise it should be function
                #print(name)
                #print(code)
                # now write out static function skeleton
                if ("extern" in code):
                    IFcode["extern"] = IFcode["extern"] + code
                elif ("CSLAB_CREATE" in code):  # global tracking mapping ds
                    IFcode["mapping ds"] = IFcode["mapping ds"] + code
                elif ("cvect_lookup" in code or "cos_map_lookup" in code):  # global tracking mapping fn
                    IFcode["mapping fn"] = IFcode["mapping fn"] + code
                #elif (name == "BLOCK_CLI_IF_CSTUB"):
                #    IFcode["cstub"] = IFcode["cstub"] + code
                else:    
                    __IFcode[name] = code
                    if (name == "BLOCK_CLI_IF_DESC_CONS"):
                        continue # do this in the init creation function
                    IFcode["internalfn_decl"] = IFcode["internalfn_decl"] + extrac_funcdecl_from_func(code)
    IFcode["global"] = __IFcode
    
    if (global_nonfun_blocks):
        __IFcode = {}
        for gblk_nonfunc in global_nonfun_blocks:
            name, code= condition_eval(gblk_nonfunc, (IFDesc[0], None))
            if (name and code):    # there should be any params, otherwise it should be function
                #print(name)
                #print(code)
                # now write out static function skeleton
                __IFcode[name] = code

    IFcode["global_non_function"] = __IFcode
    #pprint(IFcode["global_non_function"])
    #pprint(IFcode["global"])
    #exit()

def generate_ser_fblocks(result, ser_funcblocks, IFDesc, IFcode):
    IFcode["server"] = {}
    IFcode["server"]["server_code"] = {}
    IFcode["server"]["server_trackds"] = {"code":""}    
    
    #print(keywords.service_name)
    # for now. we do not recover other system services that depend on ramfs and timed_evt
    # so basically there services are the top level service and no need to track/block
    # TODO: in the future, this is possible
    if (keywords.service_name == "periodic_wake" or keywords.service_name == "ramfs"): return
    
    if (ser_funcblocks):
        for serblk in ser_funcblocks:
            #print(serblk.show())
            name, code= condition_eval(serblk, (IFDesc[0], None))
            #pprint(IFDesc[0])
            if (name and code):    # there should be any params, otherwise it should be function
                #print(name)
                #print(code)
                if (name == "BLOCK_SER_IF_TRACK_DS"):
                    IFcode["server"]["server_trackds"]["code"] = code
                else:
                    IFcode["server"]["server_code"][name] = code
    for k, v in result.tuple[0].ser_block_track.iteritems():
        IFcode["server"][k] = v
    #pprint(IFcode["server"])
    #exit()

# initial creation -- starting point in SM transition, treat this specially            
def init_creation(fdesc, subIFcode, IFcode, marshall_cp):
    code = IFcode["global"]['BLOCK_CLI_IF_BASIC_ID']
    code = code.replace("IDL_desc_saved_params", subIFcode["parameters"]["desc_params"])
    
    code = code.replace("IDL_fname", fdesc[0])
    IFcode["global"]['BLOCK_CLI_IF_BASIC_ID'] = code 
    
    #code = subIFcode["cstub_fn"]
    #code = code.replace("IDL_id", "")
    #subIFcode["cstub_fn"] = code
    #print(fdesc)
    #exit()
    # desc_cons
    #print(IFcode['global']["BLOCK_CLI_IF_DESC_CONS"])
    code = IFcode['global']["BLOCK_CLI_IF_DESC_CONS"]
    tmp = ""
    tmp_parent = ""
    for f, b in zip(subIFcode["parameters"]["desc_params"].split(","), 
                    subIFcode["parameters"]["params"].split(", ")):
        if (marshall_cp and b == marshall_cp[0]):
            tmp = tmp + f + "=" + "param_save("+ marshall_cp[0] + ", " + \
                  marshall_cp[1] +");"+ ";\n"
            continue
        tmp = tmp + f + "=" + b + ";\n"
    tmp_parent = tmp.replace("desc", "parent_desc")

    # treat the marshalled params differently (save parameterusing maloc)  
    # assume only one data being passed per invocation  
    # if (marshall_cp):
    #     tmp = tmp + "param_save("+ marshall_cp[0] + ", " + marshall_cp[1] +");"
        
    code = code.replace("IDL_parsdecl", subIFcode["parameters"]["params_decl"])
    code = code.replace("IDL_desc_cons;", tmp)
    code = code.replace("IDL_parent_desc_cons;", tmp_parent)

    IFcode['global']["BLOCK_CLI_IF_DESC_CONS"] = code
    
    # write out the declaration
    IFcode["internalfn_decl"] = IFcode["internalfn_decl"] + extrac_funcdecl_from_func(code)

def bench_mark(code, fname):
    if (keywords.bench == False):
        keywords.benchmark_meas_start = ""
        keywords.benchmark_meas_end = ""
    else:
        code = "static int IDL_fname_ubenchmark_flag;\n" + code
        
    code = code.replace("IDL_benchmark_start", keywords.benchmark_meas_start)
    code = code.replace("IDL_benchmark_end", keywords.benchmark_meas_end)
    code = code.replace("IDL_fname", fname)

    return code

def sched_timer_tick_track(subIFcode, fdesc):

    code = subIFcode["blocks"]["BLOCK_CLI_IF_TRACK"]
    if (fdesc[0] == "sched_timestamp"):
        code = code.replace("IDL_timestamp_track", keywords.sched_timestamp_track_str)
    else:
        code = code.replace("IDL_timestamp_track","")    
    subIFcode["blocks"]["BLOCK_CLI_IF_TRACK"] = code
    
    code = subIFcode["blocks"]["BLOCK_CLI_IF_DESC_UPDATE_POST_FAULT"]
    if (fdesc[0] == "sched_timeout"):
        code = code.replace("IDL_restore_ticks", "sched_restore_ticks(last_system_ticks);")
    else:
        code = code.replace("IDL_restore_ticks","")    
    subIFcode["blocks"]["BLOCK_CLI_IF_DESC_UPDATE_POST_FAULT"] = code

    code = subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"]
    if (fdesc[0] == "sched_timestamp"):
        code = code.replace("CSTUB_INVOKE", "CSTUB_INVOKE_NULL")
    subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"] = code

def deal_any_special_case_cstub(cstub_code, fdesc):
    if (fdesc[0] == "__mman_alias_page"):
        cstub_code = cstub_code.replace("IDL_special_case_1", "if (cos_spd_id() == 5) goto con;")
        cstub_code = cstub_code.replace("IDL_special_case_2", "con:")
        cstub_code = cstub_code.replace("IDL_special_case_3", "if (cos_spd_id() == 5) goto done;")
        cstub_code = cstub_code.replace("IDL_special_case_4", "done:")
    else:
        cstub_code = cstub_code.replace("IDL_special_case_1", "")
        cstub_code = cstub_code.replace("IDL_special_case_2", "")
        cstub_code = cstub_code.replace("IDL_special_case_3", "")
        cstub_code = cstub_code.replace("IDL_special_case_4", "")
    return cstub_code
    
# marshall the parameter list (using cbuf), if 2 conditions are met
# 1) more than 4 parameters (Composite passes up to 4 parameters)
# 2) passing pointer, and which is not "__retval" type
# 3) more than 1 return val
def construct_invocation_code(result, fdesc, subIFcode, IFcode, marshall_funcblocks):
    global marshalling_flag, creation_function, root_function
    subIFcode["marshall fn"] = []
    marshall_cp = []
    param_list = subIFcode["parameters"]["params"].split(", ")
    paramdecl_list = subIFcode["parameters"]["params_decl"].split(", ")
    
    cond_1 = (len(param_list) > max_params)
    cond_2 = ("*" in ', '.join(paramdecl_list))
    cond_3 = False
    ret_num = 0
    for item in paramdecl_list:
        if ("*" in item and "_retval" in item):
            ret_num += 1
            cond_3 = 1  # need treat this differently (multiple rets)
    # when either condition is met, we do the marshalling here
    if ((cond_1 or cond_2) and not cond_3):
        #print(param_list)
        #print(paramdecl_list)
        #print(fdesc[0])
        marshalling_flag = True

        tmp_cons = ""
        tmp_decl = ""
        for item in paramdecl_list:
            if ("*" in item):  # no need to pass any pointer, this is the marshalling already
                continue
            tmp_cons = tmp_cons + "md->"+item.split(" ")[1]+ " = "+ item.split(" ")[1] + ";\n"
            tmp_decl = tmp_decl + item + ";\n"
        marshalling_parsdecl = tmp_decl[:-2] # remove the last ";"
        marshalling_cons     = tmp_cons[:-2]
        
        len_var = ""
        if ("size_of" in list(traverse(fdesc))) :
            tmp_idx = list(traverse(fdesc)).index("size_of")
            data_idx = tmp_idx + 1
            len_idx = tmp_idx + 3
            len_var = list(traverse(fdesc))[len_idx]
            marshall_cp = [list(traverse(fdesc))[data_idx], list(traverse(fdesc))[len_idx]]
            ## this is the data copy before passing by cbuf
            marshalling_cons = marshalling_cons + ";\nmemcpy(&md->data[0], " + marshall_cp[0] + ", " + \
                                           marshall_cp[1] + " + 1)";
                                           
                                        
        IFcode["marshalling"] = {}
        for mblock in marshall_funcblocks:
            name, code = condition_eval(mblock, ("marshalling", None))
            if (name and code):
                IFcode["marshalling"][name] = code
                
        marshalling_ds   = IFcode["marshalling"]["BLOCK_STRUCT_MARSHALLING"]
        marshalling_ds = marshalling_ds.replace("IDL_marshalling_parsdecl", marshalling_parsdecl)        
        marshalling_code = IFcode["marshalling"]["BLOCK_CLI_IF_CSTUB_MARSHALLING"]        
        cstub_code = marshalling_code
        cstub_code = cstub_code.replace("IDL_marshalling_cons", marshalling_cons)                     
        cstub_code = cstub_code.replace("IDL_from_spd", param_list[0])
        if (len_var):
            cstub_code = cstub_code.replace("IDL_data_len", len_var)        
        inkcode = IFcode["marshalling"]["BLOCK_CLI_IF_INVOKE_MARSHALLING"] 
        inkcode = inkcode.replace("IDL_marshalling_cons", marshalling_cons)                    
        inkcode = inkcode.replace("IDL_marshalling_parsdecl", marshalling_parsdecl)
        inkcode = inkcode.replace("IDL_from_spd", param_list[0])       
        #IFcode["marshalling"]["BLOCK_CLI_IF_INVOKE_MARSHALLING"] = "" # ignore this in the final code
        
        # prepare for s_stub.S
        tmp = IFcode["s_stub.S"]
        tmp.append((fdesc[0], "__ser_"+fdesc[0]))
        IFcode["s_stub.S"] = tmp
        
        # prepare for marshalled server fn
        #pprint(IFcode["marshalling"])
        marshalling_server_fn = IFcode["marshalling"]["BLOCK_SER_IF_INVOKE_MARSHALLING"]
        unpacked_pars = []
        # here we compute the space for each passed in data
        offset = "0"
        for item in paramdecl_list:
            if ("*" in item):
                unpacked_pars. append("&md->data[" + offset + "]")
                offset = paramdecl_list[paramdecl_list.index(item)+1].split(" ")[1]
                offset = "md->"+offset + "+1"
            else:
                unpacked_pars.append("md->"+item.split(" ")[1])
        marshalling_server_fn = marshalling_server_fn.replace("IDL_marshalling_finalpars", 
                                                              ", ".join(unpacked_pars))
        marshalling_server_fn = marshalling_server_fn.replace("IDL_decl_from_spd", paramdecl_list[0])
        subIFcode["marshall fn"] = marshalling_server_fn
    else:
        #tmp = subIFcode["blocks"]["BLOCK_CLI_IF_MARSHALLING_INVOKE"].split('\n', 1)[0][:-2]+";"
        #IFcode["internalfn_decl"] = IFcode["internalfn_decl"].replace(tmp, "") # remove the static declaration
        #subIFcode["blocks"]["BLOCK_CLI_IF_MARSHALLING_INVOKE"] = "" # ignore this in the final code
        #subIFcode["marshall ds"] = ""
        
        # the wake up function no need to redo, since 
        # 1) the fault has removed the data structure, and
        # 2) reflection has woken up the "blocked" threads, 
        #    which is supposed done by the wake up function anyway 
        #pprint(subIFcode["blocks"])
        cstub_code = subIFcode["blocks"]["BLOCK_CLI_IF_CSTUB"]
        inkcode = subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"]
        marshalling_ds = ""

    # for example, mman_alias does not track booter now
    cstub_code = deal_any_special_case_cstub(cstub_code, fdesc)

    # marshalling
    subIFcode["cstub_fn"] = replace_params(result, fdesc, cstub_code, IFcode, 
                                           subIFcode, param_list, paramdecl_list)
    # for benchmark only
    subIFcode["cstub_fn"] = bench_mark(subIFcode["cstub_fn"], fdesc[0])
    
 
    subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"] = replace_params(result, fdesc, inkcode, IFcode,
                                                 subIFcode, param_list, paramdecl_list)
    
    subIFcode["marshall ds"] = replace_params(result, fdesc, marshalling_ds, IFcode, 
                                                 subIFcode, param_list, paramdecl_list)
    
    if (fdesc[0] == creation_function):
        init_creation(fdesc, subIFcode, IFcode, marshall_cp)     

    # root function can be same as creation function, however, it can also be different
    # for example, mem_mgr. This is used when recreate the root desc only
    if (fdesc[2] == "creation"):
        root_function = fdesc[0]        
    code = subIFcode["blocks"]["BLOCK_CLI_IF_TRACK"]
    code = code.replace("IDL_root_fname", root_function)
    subIFcode["blocks"]["BLOCK_CLI_IF_TRACK"] = code    
    
    # hard code for tracking tsystem ticks (e.g., sched_timestamp)
    sched_timer_tick_track(subIFcode, fdesc)  
    
    #result_code = result_code.replace()

    #print(subIFcode["cstub_fn"])
    code = subIFcode["cstub_fn"]
    #if (final_id in param_list):
    if (final_id):
        code = code.replace("IDL_id", final_id)
    else:
        code = code.replace("IDL_id, ", "")  # this is for (IDL_id, IDL_parent_id)
        code = code.replace("IDL_id", "")
        
    if (final_parent_id):
        code = code.replace("IDL_parent_id", final_parent_id)
    else:
        code = code.replace(", IDL_parent_id", "")  # this is for (IDL_id, IDL_parent_id)
        code = code.replace("IDL_parent_id", "")
    #print(code)
        
    subIFcode["cstub_fn"] = code
    #print(subIFcode["cstub_fn"])
    #print(final_id)
    #exit()
#===============================================================================
#     print(final_id)    
#     print(final_parent_id) 
#     print(param_list)
#     print(subIFcode["cstub_fn"])  # jiguo
#     exit()
#===============================================================================

    # for simplicty, manually change here for 3 rets!!!!
    if (cond_3):
        tmp = IFcode["s_stub.S"]
        tmp.append((fdesc[0], "__ser_"+fdesc[0]))
        IFcode["s_stub.S"] = tmp
        
        tmp = subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"]
        tmp = tmp.replace("CSTUB_INVOKE(ret, __fault, uc, 5, spdid, desc->server_tid, len, _retval_cbuf_off, _retval_sz);",
                          "CSTUB_INVOKE_3RETS(ret, __fault, *_retval_cbuf_off, *_retval_sz, uc, 3, spdid, desc->server_tid, len); ")
        subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"] = tmp
    #print(subIFcode["blocks"]["BLOCK_CLI_IF_INVOKE"])        

# there are 2 situations to decide if a function is creation function
# 1) has desc_data_retval (done above)
# 2) has no desc_data_retval, then sm_creation must be (done here)
def get_create_function(IFDesc):
    ret = ""
    for fdesc in IFDesc[1]:
        if any("desc_data_retval" in code and code[1] for code in fdesc[3]):
            ret = fdesc[0]
    if (ret):
        return ret
     
    # we only get here if there is no "desc_data_retval" in the cidl
    for fdesc in IFDesc[1]:
        if (fdesc[2] == "creation"):
            ret = fdesc[0]        
    return ret

def generate_fblocks(result, funcblocks, IFDesc, IFcode, marshall_funcblocks):
    global creation_function
    #no_match_code_list = []
    tmp_s_stubS = []

    creation_function = get_create_function(IFDesc)
    if not creation_function: raise Exception( "Can not find creation function" )
    
    # evaluate function blocks (and also generate cstub code here)
    for fdesc in IFDesc[1]:
        subIFcode, subIFcode["parameters"],subIFcode["blocks"], subIFcode["state"] = ({} for i in range(4)) 
        param_list, paramdecl_list, paramdesc_list = ([] for i in range(3))

        for para in fdesc[1]:               # fdesc[1] is the list of normal parameters
            param_list.append(para[1])      # para[0] is the type, para[1] is the value
            paramdesc_list.append(para[1])
            paramdecl_list.append(para[0]+" "+para[1])  # this is for the parametes used in the function decl
        subIFcode["parameters"]["params"] = ', '.join(param_list)
        subIFcode["parameters"]["params_decl"] = ', '.join(paramdecl_list)  
        
        for i in xrange(len(param_list)):
            if (param_list[i] in IFcode["trackds"]["fields"]):
                paramdesc_list[i] = "desc->"+ param_list[i]
        subIFcode["parameters"]["desc_params"] = ', '.join(paramdesc_list)
        
        # functions that not part of SM
        if (fdesc[2] == "none"):
            #IFcode[fdesc[0]] = subIFcode
            continue
        
        for fblk in funcblocks:
            #fblk.show()
            name, code = condition_eval(fblk, (IFDesc[0], fdesc))
            code = replace_params(result, fdesc, code, IFcode, 
                                  subIFcode, param_list, paramdecl_list)
            #print(name)
            #print(code)
            if (name and code):
                subIFcode["blocks"][name] = code                
                if (name != "BLOCK_CLI_IF_CSTUB"):  # cstub_fn is not normal function, no decl for it
                    # now write out static function declarations!!!
                    IFcode["internalfn_decl"] = IFcode["internalfn_decl"] + extrac_funcdecl_from_func(code)
            
        code = "IDL_fname(IDL_desc_saved_params)" # add this function to the edge later
        subIFcode["state"]["state_fn"] = replace_params(result, fdesc, code, IFcode, 
                                                        subIFcode, param_list, paramdecl_list)
        
        # decide the invocation code -- "cstub_fn and block_cli_if_invoke"
        # this is because some service might need marshalling
        construct_invocation_code(result, fdesc, subIFcode, IFcode, marshall_funcblocks)

        IFcode[fdesc[0]] = subIFcode
        #pprint(IFcode[fdesc[0]]) 
        
    #pprint (IFcode)
    #exit()
    # this is the non-match list and should be empty static inline function ?? why need this?
    #print (''.join(no_match_code_list))
    
    #IFcode["internalfn"] = IFcode["internalfn"] + '\n' + ''.join(no_match_code_list)

# construct global/function description
def generate_description(result, funcdescps, globaldescp):
    global create_new_id    
    for tup in result.tuple:
        keywords.init_service_name(result.gvars["global_info"]["service_name"])
        for key, value in tup.info.iteritems():
            if (value == "true"):    # only extract the true item
                globaldescp.append(key)

        #=======================================================================
        # # in order to generate server side block tracking and wake up code
        # for key, value in tup.ser_block_track.iteritems():
        #     print(value)
        #     globaldescp.append(key)
        # pprint(globaldescp)
        #=======================================================================
        
        for func in tup.functions:
            normalPara = func.normal_para
            idlRet  = []
            idlPara = []
            idlTime = []           
            block_or_wakeup = ""
            for key, value in func.info.iteritems():
                if (key == func.name or key == func.sm_state): # skip function name and state (only IDL stuff) 
                    continue
                elif (value and key is func.resc_data):
                    idlRet.append((key, value))
                elif (value and key is not func.desc_data_retval):
                    idlPara.append((key, value))
                elif (func.info[func.name] in tup.ser_block_track.values()):
                    block_or_wakeup = [k for k, v in tup.ser_block_track.iteritems() if v == func.info[func.name]][0]
                else:
                    (value and key is func.desc_data_retval)
                    idlRet.append((key, value))
            perFunc = (func.info[func.name], normalPara,    #--- this is the funcdescp tuple
                       func.info[func.sm_state], idlRet, idlPara, block_or_wakeup)
            #print(idlRet)
            # this indicates if a service returns a new id (e.g., mmgr does not)
            #===================================================================
            # for code in idlRet:
            #     if (code[0] == "desc_data_retval"):
            #         if (tuple(code[1]) in normalPara): create_new_id = False
            #         if (keywords.service_name == "periodic_wake"): create_new_id = False
            #===================================================================
            funcdescps.append(perFunc)
    
    # hard code these two special services that do not return new id
    if (keywords.service_name == "periodic_wake"): create_new_id = False
    if (keywords.service_name == "mem_mgr"): create_new_id = False    
    #pprint(funcdescps)
    #print(create_new_id)
    #exit()
            
#  init blocks of (predicate, code) 
def init_blocks(globalblocks, funcblocks, ser_funcblocks, marshall_funcblocks, global_nonfun_blocks):
    gblk, gblk_nonfunc, cfblk, sfblk, marshallingblk = ([] for i in range(5))
    
    keywords.build_blk_code(cfblk, sfblk, gblk, marshallingblk, gblk_nonfunc)
    # ==============================
    # 
    # fblk.append(keywords.build_fblk_code())
    # ser_fblk.append(keywords.build_ser_fblk_code())
    # gblk.append(keywords.build_gblk_code())
    #===========================================================================
    
    for item in gblk:
        globalblocks.append(item)   
    for item in cfblk:
        funcblocks.append(item)
    for item in sfblk:
        ser_funcblocks.append(item)
    for item in marshallingblk:
        marshall_funcblocks.append(item)
    for item in gblk_nonfunc:
        global_nonfun_blocks.append(item)
        
#===============================================================================
#
#   CONSTRUCT STATE MACHINE AND TRANSITION WITH THE FAULT/RECOVERY 
#
#===============================================================================
def update_current_state(result, state_list, IFcode):    
    # set the current state
    #pprint(IFcode)
    #pprint(state_list)
    
    for tup in result.tuple:
        for func in tup.functions:
            for item in state_list:
                if (func.info[func.name] == item.split("state_")[1]):
                    code = IFcode[func.info[func.name]]["blocks"]["BLOCK_CLI_IF_TRACK"]
                    code = code.replace("IDL_curr_state", "desc->state = " + str(item))
                    IFcode[func.info[func.name]]["blocks"]["BLOCK_CLI_IF_TRACK"]  = code
                else:
                    if (func.info[func.sm_state]) == "none": continue
                    code = IFcode[func.info[func.name]]["blocks"]["BLOCK_CLI_IF_TRACK"]
                    code = code.replace("IDL_curr_state;", "")
                    IFcode[func.info[func.name]]["blocks"]["BLOCK_CLI_IF_TRACK"]  = code

def construct_sm_graph(from_list, to_list, state_list, IFcode):
    smg = Graph(directed=True)
    smg.add_vertices(state_list)
    
    smg.add_edges(zip(from_list,to_list))
        
    for e in smg.es:
        fn = smg.vs[e.target]["name"].replace("state_","")
        e["func"] = IFcode[fn]["state"]["state_fn"]

        if (e.source == e.target):
            e["retcode"] = "again"
        else:
            e["retcode"] = "ok"
    
    #pprint(IFcode)
    #exit()
    for item in state_list:
        if (item == "state_null"):
            continue
        fn = state_list[0].replace("state_", "")  # get the actual transition function (recreate)
        smg.add_edge(item, state_list[0], retcode = "faulty", func = IFcode[fn]["state"]["state_fn"])
    return smg

def generate_sm_transition(result, funcblocks, IFcode):     
    fn_list, state_list, \
    transition_list_tuple, transition_list_code, \
    from_list, to_list = ([] for i in range(6))
    
    for tup in result.tuple:
        # here we fix the start and end to be 1st and 2nd in the list
        for func in tup.functions:
            if (func.info[func.sm_state] == "creation"):
                fn_list.insert(0, func.info[func.name])
                state_list.insert(0, "state_"+func.info[func.name])
            elif (func.info[func.sm_state] == "terminal"):
                fn_list.insert(1, func.info[func.name])
                state_list.insert(1, "state_"+func.info[func.name])
            elif (func.info[func.sm_state] == "transition"):
                fn_list.append(func.info[func.name])
                state_list.append("state_"+func.info[func.name])
        state_list.append("state_null")
        
        for k, v in tup.sm_info.items():
            for item in v:
                if (item[1] == "end"):  # does not count the end state
                    continue
                from_list.append("state_" + item[0])
                to_list.append("state_" + item[1])
                
                if (item[0] != item[1]):
                    tmp_str = "ok"
                else:
                    tmp_str = "again"
                    
                if (item[1] == "none"):
                    fn_str = "(generic_fp)" + item[0]
                else:
                    fn_str = "(generic_fp)" + item[1]
                    
                transition_list_code.append("{"+ "state_"+ item[0] + ", " + 
                                       "state_" + item[1] + ", " + tmp_str + ", " +  
                                       fn_str + "}" +",\n")
                transition_list_tuple.append((item[0], item[1], tmp_str, fn_str))

    #pprint(IFcode)
    #pprint(state_list)
    #pprint(transition_list_tuple)
    #pprint(transition_list_code)
    #exit()

    code = IFcode["global_non_function"]["BLOCK_CLI_IF_TRACKING_STATE"]
    code = code.replace("IDL_state_list", ', '.join(state_list))
    code = code.replace("IDL_transition_rules", ' '.join(transition_list_code))
    IFcode["global_non_function"]["BLOCK_CLI_IF_TRACKING_STATE"] = code

    # update the initial state in BLOCK_BASIC
    code = IFcode["global"]["BLOCK_CLI_IF_BASIC_ID"]
    code = code.replace("IDL_init_state", state_list[0])
    IFcode["global"]["BLOCK_CLI_IF_BASIC_ID"] = code

    # update the SM state and transition function for recovery
    update_current_state(result, state_list, IFcode) 
    smg = construct_sm_graph(from_list, to_list, state_list, IFcode)

    #pprint(from_list)
    #pprint(to_list)
    #pprint(state_list)
    #exit()
    
    # this is the key to the c3 recovery
    recover_sm_transition(state_list, smg, IFcode)

    # plot the state transition
    if (keywords.plot_graph == True):      
        keywords.draw_sm_transition(smg)
    return smg
    
# ***********!!!!!!!!*************
# find the state transition path
# ***********!!!!!!!!************
# On the SM graph, the fault can happen when the transition is happenning from a state to another state.
# The red line represents the first transition from the fault state with the transition function  
# For example, the fault state can be transited to the state_tsplit by executing tsplit. 
# Or the fault state can be transited to the previous state by not doing any thing
# Then the "replay" in the C^3 can be applied 
#
# Note: the recover path must be able to reach to the target state. Therefore, smg should be able to support 
#       reachability check (i.e., among all possible paths, select the shortest path)
def recover_sm_transition(state_list, smg, IFcode):
    rec_path = {}
    rec_code = ""
    
    transition_code = IFcode["global_non_function"]["BLOCK_CLI_IF_STATE_TRANSITION"]
    #creation_v = smg.vs.find(name = state_list[0])   # creation node
    creation_v = smg.vs.find(name = "state_" + creation_function)
    
#===============================================================================
#     print(state_list)
#     print(creation_function)
#     print(transition_code)
#     print(creation_v)    
#     print(state_list)
# 
#     exit()
#===============================================================================
    for item in state_list:
        tmp_dict = {}
        if (item == "state_null"):
            continue
        other_v = smg.vs.find(name = item)
        
        # condition 1: for wakeup function, no need to find a path. See "cstub no redo"
        if ("wakeup" in IFcode["server"]):
            if (item.replace("state_", "") == IFcode["server"]["wakeup"]):
                continue;

        back_edges = smg.get_shortest_paths(creation_v.index, other_v.index, 
                                                mode = 'OUTPUT', output="epath")
        # does not include the last function call (will be done by "redo")
        # back_edges.pop()
        
        #print(creation_v["name"])
        #print(other_v["name"])
        #print(back_edges)
        #print()
        
        _tmp = transition_code.replace("IDL_current_state", state_list[0])
        _tmp = _tmp.replace("IDL_next_state", item)
                
        recfn_list = []
        for _eidx in back_edges:
            if (_eidx):                
                for eid in _eidx:
                    # condition 2: only add the function that has not reached the destination
                    if (item == smg.vs(smg.es[eid].target)["name"][0]): 
                        continue;
                    #print(smg.es[eid]["func"].rsplit('(',1)[0])
                    #print(IFcode[smg.es[eid]["func"].rsplit('(',1)[0]]["parameters"]["desc_params"])
                    tmp_deslparams = IFcode[smg.es[eid]["func"].rsplit('(',1)[0]]["parameters"]["desc_params"]
                    tmp_code = smg.es[eid]["func"]
                    tmp_code = tmp_code.replace("IDL_desc_saved_params", tmp_deslparams)
                    recfn_list.append(tmp_code)
                        
        if (recfn_list):
            rec_path[(state_list[0], item)] = recfn_list
            s = ""
            for item in recfn_list:
                s = s + item + ";\n"
            _tmp = _tmp.replace("IDL_state_transition_call", s)           
            rec_code = rec_code + _tmp

    code = IFcode['global']["BLOCK_CLI_IF_CALL_DESC_UPDATE"]
    code = code.replace("IDL_state_transition;", rec_code)
    IFcode['global']["BLOCK_CLI_IF_CALL_DESC_UPDATE"] = code
    
    #===========================================================================
    #     
    #     # add the creation function (only one creation function)
    #     _tmp = transition_code.replace("IDL_current_state", before)
    #     _tmp = _tmp.replace("IDL_next_state", after)
    #     s = ""
    #     # then add each function along the rec_path
    #     if ("rec_steps" in tmp_dict): 
    #         for item in tmp_dict["rec_steps"]:
    #             s = s + item[0]
    #     _tmp = _tmp.replace("IDL_state_transition_call", s)
    #     tmp = tmp + _tmp
    # 
    # exit()
    #===========================================================================

#=========================
#
#  CODE GENERATING
#
#=========================
def lookup_funcname(result, sm_type):
    fname = ""
    for tup in result.tuple:
        for func in tup.functions:
            if (func.info[func.sm_state] == sm_type):            
                fname = func.info["funcname"]
    return fname

def lookup_functype(result, fn_name):
    ftype = ""
    for tup in result.tuple:
        for func in tup.functions:
            if (func.info["funcname"] == fn_name):            
                ftype = func.info["functype"]
    return ftype

def construct_server_code(result, IFcode):
    server_code = ""  
    IFresult = {}
    IFresult["SERVER"] = {}
    if ("server_trackds" in IFcode["server"]): # some service does not have server inteface code
        IFresult["SERVER"]  = {"tracds" : IFcode["server"]["server_trackds"]["code"]}
        server_code = "\n" + server_code + IFresult["SERVER"]["tracds"]
    IFresult["SERVER"]["block_func"] = {}
    IFresult["SERVER"]["wakeup_func"] = {}
    IFresult["SERVER"]["create_exist_func"] = {}
    IFresult["SERVER"]["save_data"] = {}
    IFresult["SERVER"]["restore_data"] = {}
    
    for k, v in IFcode["server"]["server_code"].items():
        if ("BLOCK_SER_IF_RECREATE_EXIST" == k):  # 
            
            func_name = lookup_funcname(result, "creation")            
            tmp_par = IFcode[func_name]["parameters"]["params"]
            from_spd = tmp_par.split(',')[0]
                              
            v = v.replace("IDL_fname", func_name)
            v = v.replace("IDL_parsdecl", IFcode[func_name]["parameters"]["params_decl"])
            v = v.replace("IDL_from_spd", from_spd)
            v = v.replace("IDL_params", tmp_par)
            v = v.replace("IDL_fntype", lookup_functype(result, func_name))
            if ("lock_take_func" in IFcode):
                v = v.replace("IDL_TAKE", IFcode["lock_take_func"])
            if ("lock_release_func" in IFcode):
                v = v.replace("IDL_RELEASE", IFcode["lock_release_func"])  
                 
            IFresult["SERVER"]["create_exist_func"] = v
            server_code = server_code + v
            
            func_name = func_name+"_exist"
            # prepare for s_stub.S
            tmp = IFcode["s_stub.S"]
            tmp.append((func_name, "__ser_"+func_name))
            IFcode["s_stub.S"] = tmp
                    
        elif ("BLOCK_SER_IF_BLOCK_TRACK" == k):  # block
            
            func_name = IFcode["server"]["server_block"]
            tmp_par = IFcode[func_name]["parameters"]["params"]
            from_spd = tmp_par.split(',')[0]
                             
            v = v.replace("IDL_fname", func_name)
            v = v.replace("IDL_parsdecl", IFcode[func_name]["parameters"]["params_decl"])
            v = v.replace("IDL_from_spd", from_spd)
            v = v.replace("IDL_params", tmp_par)
            v = v.replace("IDL_fntype", lookup_functype(result, func_name))
            if ("lock_take_func" in IFcode):
                v = v.replace("IDL_TAKE", IFcode["lock_take_func"])
                v = v.replace("IDL_RELEASE", IFcode["lock_release_func"])

            IFresult["SERVER"]["block_func"]["code"] = v
            server_code = server_code + v

            # prepare for s_stub.S
            tmp = IFcode["s_stub.S"]
            tmp.append((func_name, "__ser_"+func_name))
            IFcode["s_stub.S"] = tmp

                        
        elif ("BLOCK_SER_IF_CLIENT_FAULT_NOTIFICATION" == k):  # wakeup
            
            func_name = IFcode["server"]["server_wakeup"]            
            tmp_par = IFcode[func_name]["parameters"]["params_decl"]
            from_spd = tmp_par.split(',')[0].split(' ')[1]            
            tmp_par = IFcode[func_name]["parameters"]["params"]
            tmp_par = tmp_par.replace(final_id, "tb->"+final_id)  
                      
            v = v.replace("IDL_fname", func_name)
            v = v.replace("IDL_parsdecl", IFcode[func_name]["parameters"]["params_decl"])
            v = v.replace("IDL_from_spd", from_spd)
            v = v.replace("IDL_params", tmp_par)
            v = v.replace("IDL_fntype", lookup_functype(result, func_name))
            if ("lock_take_func" in IFcode):
                v = v.replace("IDL_TAKE", IFcode["lock_take_func"])
                v = v.replace("IDL_RELEASE", IFcode["lock_release_func"])            
           
            IFresult["SERVER"]["wakeup_func"]["code"] = v            
            server_code = server_code + v            

            # prepare for s_stub.S
            tmp = IFcode["s_stub.S"]
            tmp.append((keywords.service_name + "_client_fault_notification",
                        "__ser_" + keywords.service_name + "_client_fault_notification"))
            IFcode["s_stub.S"] = tmp

        elif ("BLOCK_SER_IF_SAVE_DATA" == k):  # save data at the server interface
            func_name = ""
            for tup in result.tuple:
                for func in tup.functions:
                    if (func.info[func.resc_data]):
                        func_name = func.info["funcname"]
                        break
            tmp_par = IFcode[func_name]["parameters"]["params"]
            v = v.replace("IDL_fname", func_name)
            v = v.replace("IDL_parsdecl", IFcode[func_name]["parameters"]["params_decl"])
            v = v.replace("IDL_params", tmp_par)
            v = v.replace("IDL_fntype", lookup_functype(result, func_name))

            IFresult["SERVER"]["save_data"]["code"] = v
            server_code = server_code + v

            # prepare for s_stub.S
            tmp = IFcode["s_stub.S"]
            tmp.append((func_name, "__ser_IDL_service_save_data_"+func_name))
            IFcode["s_stub.S"] = tmp

        elif ("BLOCK_SER_IF_RESTORE_DATA" == k):  # restore data at the server interface
            func_name = ""
            for tup in result.tuple:
                for func in tup.functions:
                    if (func.info[func.resc_data]):
                        func_name = func.info["funcname"]
                        break
            tmp_par = IFcode[func_name]["parameters"]["params"]
            v = v.replace("IDL_fname", func_name)
            v = v.replace("IDL_parsdecl", IFcode[func_name]["parameters"]["params_decl"])
            v = v.replace("IDL_params", tmp_par)
            v = v.replace("IDL_fntype", lookup_functype(result, func_name))

            IFresult["SERVER"]["restore_data"]["code"] = v
            server_code = server_code + v

            # prepare for s_stub.S
            tmp = IFcode["s_stub.S"]
            tmp.append((keywords.service_name + "_restore_data_"+func_name,
                        "__ser_" + keywords.service_name + "_restore_data_"+func_name))
            IFcode["s_stub.S"] = tmp
            
    #print(server_code)
    #print(IFcode["s_stub.S"])
    
    #exit()
    marshall_fn = ""
    for fn in result.tuple[0].functions:
        fname = fn.info["funcname"]
        if (fname in IFcode and 
            "marshall fn" in IFcode[fname] and
            IFcode[fname]["marshall fn"]):
            marshall_fn = marshall_fn + IFcode[fname]["marshall fn"]
            marshall_fn = IFcode[fname]["marshall ds"] + marshall_fn
            marshall_fn = marshall_fn.replace("IDL_fname", fname)
            marshall_fn = marshall_fn.replace("IDL_fntype", fn.info["functype"])
            
    server_code = marshall_fn + server_code
    server_code = server_code.replace("IDL_service", keywords.service_name)
    server_code = server_code.replace("IDL_id", final_id)
    
    # # on server side, we add "extern" for the final code
    # if (keywords.final_output == True):     
    #     extern_fn = ""
    #     for fn in result.tuple[0].functions:
    #         extern_fn = extern_fn + "extern " + fn.info["functype"] + " " + \
    #                     fn.info["funcname"] + "(" + \
    #                     IFcode[fn.info["funcname"]]["parameters"]["params_decl"] + ");\n"

    #     server_code = extern_fn + server_code

    # the service is using the lock service (use optimized client lock)
    if (keywords.final_output == True 
        and "lock_take_func" in IFcode 
        and "lock_take" in IFcode["lock_take_func"]):
        if (keywords.service_name != "sched"):
            lock_header = '''
            #include <cos_synchronization.h>
            extern IDL_lock_name
            
            '''
        else:
            lock_header = '''
            #include <../../../implementation/sched/cos_sched_sync.h>
            '''
            
        server_code =  lock_header + server_code
        server_code = server_code.replace("IDL_lock_name", IFcode["lock_name"])
        
    #===========================================================================
    # server_code = server_code.replace("IDL_TAKE", IFcode["lock_take_func"])
    # server_code = server_code.replace("IDL_RELEASE", IFcode["lock_release_func"])
    #===========================================================================

    # hard code treadp (3rets)
    if (keywords.service_name == "ramfs"):
        server_code = keywords.ser_treadp_str + server_code
    
    # for example, mem_mgr has the nameserver valloc and evt has the nameserver evt_ns
    if (keywords.service_name in keywords.nameserver):
        server_code = server_code.replace("IDL_nameserver_recover_call", keywords.nameserver[keywords.service_name])
    # replace the type of desc id
    server_code = server_code.replace("IDLidtype", final_id_type)
    server_code = server_code.replace("IDLparentidtype", final_parent_id_type)
    
    return server_code

def construct_client_code(result, IFcode):
    result_code = ""
    tmp, IFresult = ({} for i in range(2))
    
    # reorgonize the code section
    IFresult["GLOBAL"]  = {"global_blks":IFcode["global"],    # multiple blocks
                           "extern_fn":IFcode["extern"],
                           "tracking_ds":IFcode["trackds"]["code"],
                           "internal_fn_decl":IFcode["internalfn_decl"],
                           "mapping ds":IFcode["mapping ds"],
                           "mapping fn":IFcode["mapping fn"]}
    
    IFresult["SM"]      = {"state_group":IFcode["global_non_function"]["BLOCK_CLI_IF_TRACKING_STATE"]} 
    
    for tup in result.tuple:
        for func in tup.functions:
            name = func.info["funcname"]
            if (name in IFcode): tmp[name]= IFcode[name]
    IFresult["FUNCTIONS"] = tmp
 
    # start pasting the code
    #if (keywords.service_name != "scheduler"):
    result_code = result_code + IFresult["GLOBAL"]["tracking_ds"]
    result_code = result_code + "\n"
    result_code = result_code + IFresult["GLOBAL"]["mapping ds"]
    result_code = result_code + "\n"
    result_code = result_code + IFresult["GLOBAL"]["mapping fn"] 
    result_code = result_code + "\n"   

    for k, v in IFresult["FUNCTIONS"].items():
        if ("marshall ds" in v): result_code = result_code + v["marshall ds"]
    result_code = result_code + "\n"
    
    
    result_code = result_code + IFresult["SM"]["state_group"]
    result_code = result_code + "\n"    
   
    result_code = result_code + IFresult["GLOBAL"]["extern_fn"]
    result_code = result_code + "\n"

    result_code = result_code + IFresult["GLOBAL"]["internal_fn_decl"]
    result_code = result_code + "\n"
    
    #result_code = result_code + IFresult["GLOBAL"]["internal_fn"]
    #result_code = result_code + "\n"    
    
    
    #pprint(IFcode)
    for k, v in IFresult["GLOBAL"]["global_blks"].items():
        result_code = result_code + v
        
    # in case that the service has dependency and does not need to recover the root
    if (keywords.service_name in keywords.rootid):
        result_code = result_code.replace("IDL_root_id", keywords.rootid[keywords.service_name])

    for k, v in IFresult["FUNCTIONS"].items():
        for _k, _v in v["blocks"].items():
            if (_k == "BLOCK_CLI_IF_TRACK"):
                if (keywords.service_name == "sched"): # scheduler is special
                    _v = _v.replace("IDL_id", "cos_get_thd_id()")
                    #_v = _v.replace("state_sched_timeout", "0")
                    #_v = _v.replace("state_sched_component_release", "0")
                    #_v = _v.replace("state_sched_component_take", "0")
                    _v = _v.replace("desc->cos_get_thd_id()", "desc->IDL_id")                    
            if (_k == "BLOCK_CLI_IF_CSTUB"): # cstub_fn is not normal function (e.g., marshal) - use "cstub_fn" 
                continue
            result_code = result_code + _v
            
    for k, v in IFresult["FUNCTIONS"].items():
        if ("cstub_fn" in v): result_code = result_code + v["cstub_fn"]
        
    # finally replace IDL_id, IDL_server_id, IDL_parent_id
    result_code = result_code.replace("IDL_id", final_id)
    result_code = result_code.replace("IDL_server_id", "server_" + final_id)
    
    if ("desc_parent id" in IFcode["trackds"]):
        result_code = result_code.replace("IDL_parent_id", final_parent_id)
    if ("desc_parent component" in IFcode["trackds"]):
        result_code = result_code.replace("IDL_parent_spd", final_parent_component)

    if (keywords.final_output == True):
        result_code = result_code.replace("IDL_init_maps", keywords.init_map_str)
    else:
        result_code = result_code.replace("IDL_init_maps", "")

    # for example, desc_maps now changes to ILD_service_desc_maps
    result_code = result_code.replace("IDL_service", keywords.service_name)
    
    # for example, mem_mgr has the nameserver valloc and evt has the nameserver evt_ns
    if (keywords.service_name in keywords.nameserver):
        result_code = result_code.replace("IDL_nameserver_recover_call", keywords.nameserver[keywords.service_name])

    if (marshalling_flag == True):
        result_code = keywords.para_save_str + result_code
    
    # replace the type of desc id    
    result_code = result_code.replace("IDLidtype", final_id_type)
    result_code = result_code.replace("IDLparentidtype", final_parent_id_type)
    
    
    #print(root_function)
    tmp = IFcode[root_function]["parameters"]["params"]
    if ("flags" in tmp): tmp = tmp.replace("flags", "0")
    result_code = result_code.replace("IDL_root_params", tmp)
    # hard code sched timeout and timestamp
    #result_code = result_code.replace("state_sched_timestamp", "0")
    #result_code = result_code.replace("state_sched_timeout", "0")
    #exit()
    return result_code

def construct_header(result, IFcode):
    header_code = ""

    for tup in result.tuple:
        for func in tup.functions:
            if (func.info["funcsm"] == "creation" and (keywords.service_name != "sched" and (desc_global or (not create_new_id)))):
                fnname  = func.info["funcname"]+"_exist"
                fntype  = func.info["functype"]
                fnparamsdecl = IFcode[func.info["funcname"]]["parameters"]["params_decl"] + \
                                ", IDLidtype IDL_id"
                header_code = header_code + fntype +" " + fnname + "(" + fnparamsdecl + ");\n"
            elif (func.info[func.resc_data]):
                fnname = func.info["funcname"]
                fntype = lookup_functype(result, fnname)
                fnparamsdecl = IFcode[fnname]["parameters"]["params"]
                #tmp_name = keywords.service_name + "_save_data_" + fnname 
                #header_code = header_code + fntype +" " + tmp_name + "(" + fnparamsdecl + ");\n"
                tmp_name = keywords.service_name + "_restore_data_" + fnname 
                header_code = header_code + fntype +" " + tmp_name + "(" + fnparamsdecl + ");\n"

    if (desc_global and desc_dep_create_same):
        header_code = header_code + "int "+keywords.service_name+\
                    "_upcall_creator(spdid_t spdid, IDLidtype IDL_id);\n\n"    
        
    if (desc_global and (not desc_dep_create_none)):
        header_code = header_code + "extern void "+ keywords.service_name +\
                      "_cli_if_recover_upcall_entry(IDLidtype IDL_id);\n"
                      
    if (desc_global and desc_close_subtree):
        header_code = header_code + "extern void "+ keywords.service_name +\
                      "_cli_if_recover_upcall_subtree_entry(IDLidtype IDL_id);\n"
        header_code = header_code + "extern void "+ keywords.service_name +\
                      "_cli_if_remove_upcall_subtree_entry(IDLidtype IDL_id);\n"

    # !!! Do not use per function predicate here
    
    if ("BLOCK_SER_IF_BLOCK_TRACK" in IFcode["server"]["server_code"]):
        header_code = header_code + "void " + keywords.service_name + \
                      "_client_fault_notification"+"(spdid_t spdid);\n"
    
    header_code = header_code.replace("IDLidtype", final_id_type)
    header_code = header_code.replace("IDL_id", final_id)
    
    cos_header = keywords.cos_header_dict[keywords.service_name]  
    f = open(cos_header, 'r')
    origin_header = f.readlines()
    f.close()
    origin_header.insert(-1, IDL_banner)
    origin_header.insert(-1, '''#include <c3_test.h> ''' + "\n")
    origin_header.insert(-1, header_code)
    #print("".join(origin_header))
    #exit()
    header_code = "".join(origin_header)           
    
    #print(header_code)
    #exit()
    return header_code

def construct_s_stub_code(result, IFcode):
#===============================================================================
#     result_code = """
# /* How IDL know when to use simple stack or stack? */
# #include <cos_asm_server_stub_simple_stack.h>
# //#include <cos_asm_server_stub.h>
#     
# .text
#     """
#     #asm_dict
#===============================================================================
    cos_asm = keywords.cos_asm_dict[keywords.service_name]  
    f = open(cos_asm, 'r')
    origin_cos_asm = f.readlines()
    f.close()
    
    test = ""
    result_code = ""
    tmp_list = []
    for item in IFcode["s_stub.S"]:
        result_code = result_code + "\ncos_asm_server_fn_stub_spdid(" + item[0] + "," + item[1]+ ")"
        tmp_list.append(item[0])
        for line in origin_cos_asm:
            if ("(" in line and "," not in line): 
                if (item[0] == line[line.index("(") + 1:line.rindex(")")]):
                    # if find an existing one, remove it, and replace with the new one
                    origin_cos_asm.remove(line)
                    break;
            if ("(" in line and "," in line):
                if (item[0] == line[line.index("(") + 1:line.rindex(",")]):
                    # if find an existing one (fn version), remove it, and replace with the new one
                    origin_cos_asm.remove(line)
                    break;

    result_code = "".join(origin_cos_asm) + result_code
        
    if (desc_global and desc_dep_create_same):
        result_code = result_code + "\ncos_asm_server_stub_spdid(" + creation_function + "_exist" + ")"
    if (desc_global and desc_dep_create_diff):
        result_code = result_code + "\ncos_asm_server_stub_spdid(" + root_function + "_exist" + ")"
    if (not desc_global and not create_new_id):
        result_code = result_code + "\ncos_asm_server_stub_spdid(" + creation_function + "_exist" + ")"
    if (desc_global and desc_dep_create_same):
        result_code = result_code + "\ncos_asm_server_stub_spdid("+keywords.service_name +"_upcall_creator)"
        

    # hard code these for now (ramfs uses twmeta to restore data, but not from client)
    # this can be auto generated TODO this later
    result_code = result_code.replace("cos_asm_server_fn_stub_spdid(trmeta, __sg_trmeta)",
                                      "cos_asm_server_stub_spdid(trmeta)")
    result_code = result_code.replace("cos_asm_server_fn_stub_spdid(twmeta, __sg_twmeta)",
                                      "cos_asm_server_stub_spdid(twmeta)")    
    result_code = result_code.replace("cos_asm_server_fn_stub_spdid(tmerge, __sg_tmerge)",
                                      "cos_asm_server_stub_spdid(tmerge)")    
    
    #print(result_code)
    #exit()
    result_code = result_code.replace("IDL_service", keywords.service_name)
    return result_code
    
def write_code_to_file(code, output_file):
    if(write_to_file == 0):
        return
    
    # write out the result to the file (easier debug)    
    if (output_file[-1] != "c"):
        with open(output_file, "w") as text_file:
            text_file.write("{0}".format(code))
        return

    #pprint(IFcode)
    #exit()
    if (keywords.final_output == False):    
        # make a fake main function for testing only        
        if (using_main):
            fake_main = r"""
    /* this is just a fake main function for testing. Remove it later  */
    int main()
    {
        return 0;
    }
    """
            code = code + "\n" + fake_main
        
        #code = r'''#include "cidl_gen.h"''' + "\n" + code
        code = r'''#include "fake_header.h"''' + "\n" + code

       
    with open("tmp.c", "w") as text_file:
        text_file.write("{0}".format(code))
    os.system("indent -linux tmp.c -o " + output_file)
    os.system("rm tmp.c")

    if (keywords.final_output == False): 
        # generate the new ast for the interface code (only for c file)
        parser = c_parser.CParser()
        ast = parse_file(output_file, use_cpp=True,
                         cpp_path='cpp',
                         cpp_args=r'-Iutils/fake_libc_include')
        #ast.show()

def paste_idl_code(result, IFcode):
    global  IDL_banner
    
    IDL_banner = "/* " + keywords.IDL_ver + " ---  " + time.strftime("%c") + " */\n\n"    
    sname = keywords.service_name

    if (keywords.final_output == True):
        sname = "final_" + sname

    # client side code
    client_code = construct_client_code(result, IFcode)
    if (keywords.bench == True):
        client_code = keywords.benchmark_vars + client_code
    if (keywords.final_output == True):
        if (keywords.service_name == "ramfs"):
            client_code = IDL_banner + keywords.add_c_header("torrent") + client_code
        else:
            client_code = IDL_banner + keywords.add_c_header(keywords.service_name) + client_code
    write_code_to_file(client_code, "output/" + sname + "_c_stub.c")  
    
    # server side code
    server_code = construct_server_code(result, IFcode)
    if (keywords.final_output == True):
        if (keywords.service_name == "ramfs"):
            server_code = IDL_banner + keywords.add_c_header("torrent") + server_code
        else:
            server_code = IDL_banner + keywords.add_c_header(keywords.service_name) + server_code
    write_code_to_file(server_code, "output/" + sname + "_s_cstub.c")
    
    # header file
    header_code = construct_header(result, IFcode)
    #if (keywords.final_output == True):
    #    header_code = IDL_banner + header_code
    write_code_to_file(header_code, "output/" + sname + "_idlc3.h")
    
    # s_stub.S
    s_stub_code = construct_s_stub_code(result, IFcode)
    s_stub_code = IDL_banner + s_stub_code
    write_code_to_file(s_stub_code, "output/" + sname + "_s_stub.S")

    print ("\n<<<IDL process is done!!>>>")

def idl_generate(result, parsed_ast):
    globaldescp, funcdescps, globalblocks, global_nonfun_blocks,\
    funcblocks, ser_funcblocks, marshall_funcblocks= ([] for i in range(7))
    IFcode          = {}
    
    #===========================================================================
    # pprint (result.tuple[0].info)
    # pprint (result.tuple[0].sm_info)
    # pprint (result.tuple[0].ser_block_track)
    # pprint (result.tuple[0].desc_data_fields)
    # pprint (result.gvars)
    # pprint (result.tuple[0].functions[0].info)
    # pprint (result.tuple[0].functions[1].info)
    # pprint (result.tuple[0].functions[2].info)
    # pprint (result.tuple[0].functions[3].info)
    # exit()
    #===========================================================================

    #keywords.read_from_template_code(IFcode)    
    IFDesc = (globaldescp, funcdescps)
    
    # build blocks and descriptions
    generate_description(result, funcdescps, globaldescp)
    init_blocks(globalblocks, funcblocks, ser_funcblocks, marshall_funcblocks, global_nonfun_blocks)
    #pprint(funcdescps)
    # evaluate the conditions and generate block code
    generate_gblocks(result, globalblocks, global_nonfun_blocks, IFDesc, IFcode)
    generate_globalvas(result, IFcode)
    # server side code
    generate_ser_fblocks(result, ser_funcblocks, IFDesc, IFcode)
    # client side code
    generate_fblocks(result, funcblocks, IFDesc, IFcode, marshall_funcblocks)

    # add SM transition code
    generate_sm_transition(result, funcblocks, IFcode)

    #print(IFcode["global"]["BLOCK_CLI_IF_UPCALL_CREATOR"])
    #print(IFcode["global"]["BLOCK_CLI_IF_TRACKING_MAP_DS"])
    #pprint(IFcode)
    
    #pprint(IFcode["global"])
    #pprint(IFcode["server_trackds"]["code"])
    #print(IFcode["server"]["server_code"]["BLOCK_SER_IF_RECREATE_EXIST"])
    #print(IFcode["internalfn"])
    #print(IFcode["internalfn_decl"])
    #for item in globalblocks:
    #    item.show()
    #exit()
    paste_idl_code(result, IFcode)   # make some further IFprocess here
    
    #pprint(IFcode)
