#!/usr/bin/python
# title            :c3_parser.py
# description      :This script preprocesses the IDL language mostly defined in macro 
#                  and send to the 2nd stage to generagte the AST and the final interface code in C
# author           :Jiguo Song
# date             :20150817
# version          :0.1
# notes            :
# python_version   :2.6.6
#
# Input : this file should run on the defined macros in cidl_gen.h and cidl.h
# Output: interface recovery code in C 
#==============================================================================

# Rules For Constructing Variable Name
#
#  Characters Allowed :
#     Underscore(_)
#     Capital Letters (A-Z)
#     Small Letters (a-z)
#     Digits (0-9)
#
#  Blanks & Commas are not allowed
#  No Special Symbols other than underscore(_) are allowed
#  First Character should be alphabet or Underscore
#  Variable name Should not be Reserved Word

# We define the following delimiter:
#  SCD -- Start of C3 Delimiter
#  ECD -- End of C3 Delimiter
#  CD --  C3 Delimiter

from __future__ import print_function
import sys, os, re 
#from pprint import pprint
from pycparser import parse_file, preprocess_file
from pycparser import c_parser, c_ast, c_generator
sys.path.extend(['.', '..'])

import c3_gen, keywords
from pprint import pprint

#get_desc_track_struct(result, node);

idl_parse_func_result = []  # global string to save parsed func info
idl_parse_tuple_result = []  # global string to save parsed tuple info

def get_class_name(node):
    return node.__class__.__name__
       
def get_type_name(node):
    return node.type.type.type.names

def get_dec_type_name(node):
    return node.type.type.names
       
def parse_idl_str(delimiter, mystr):
    ret = []    

    pattern = "(?<=" + delimiter + ")(?:(?!" + \
              delimiter + ").){5,}(?=" + delimiter + ")"

    last_str = ""
    for match in re.finditer(pattern, mystr, re.I):
        result_str = match.group()
        result_str = result_str[1:-1]
        ret.append(result_str)
        last_str = mystr[match.end() + len(delimiter):]
        last_str = last_str[1:]
    ret.append(last_str)    
    return ret

def traverse(o, tree_types=(list, tuple)):
    if isinstance(o, tree_types):
        for value in o:
            for subvalue in traverse(value, tree_types):
                yield subvalue
    else:
        yield o
    
#===============================================================================
# # Decl: [name, quals, storage, funcspec, type*, init*, bitsize*]
# # field is Decl  
#
#  This is used to construct State Machine information
#===============================================================================
class DeclVisitor(c_ast.NodeVisitor):
    def visit_Decl(self, node):
        parse_decl_info(node)
        
def parse_decl_info(node):
    #print (node.name)
    if (node.name is None):
        return
    else:
        ret = parse_idl_str('SM', node.name)
      
    if (ret[0] == "creation" or ret[0] == "terminal"):
        result.tuple[-1].sm_info[ret[0]] = ret[1]
    elif (ret[0] == "transition"):
        transition_list.append((ret[1], ret[2]))
        result.tuple[-1].sm_info[ret[0]] = transition_list
      
#===============================================================================
# # Struct: [name, decls**]
# # struct is node.decls  --> decl list (node is Struct)
# 
# # Decl: [name, quals, storage, funcspec, type*, init*, bitsize*]
# # field is Decl  
#   
# # TypeDecl: [declname, quals, type*]  
# # field.type is TypeDecl  
# 
# # IdentifierType: [names]
# # field.type.tpye is IdentifierType  
#
#  This is used to construct global information (e.g., tuple in the paper)
#===============================================================================
class StructVisitor(c_ast.NodeVisitor):
    def visit_Struct(self, node):
        #global result
        #result.add_tuple()
        ret = parse_structure_info(node)
        
def parse_structure_info(node):
    struct  = node.decls
    #print (node.name)
    for field in struct:
        tmp = get_class_name(field.type)
        if (tmp == keywords.ptrdecl):
            key = "".join(field.type.type.type.names) + " *"
        elif (tmp == keywords.typedecl):
            key = "".join(field.type.type.names)
        elif (tmp == keywords.funcdecl):
            print ("keywords is function decl")
        val = field.name
        if (node.name == "global_info"):
            result.tuple[-1].info[key] = val
            result.gvars[node.name] = result.tuple[-1].info
        elif (node.name == "func_sm"):
            result.tuple[-1].sm_info[key] = val
            result.gvars[node.name] = result.tuple[-1].sm_info
        elif (node.name == "desc_data"):
            result.tuple[-1].desc_data_fields.append([key,val])
            result.gvars[node.name] = result.tuple[-1].desc_data_fields
    #pprint(result.gvars)
    
#===============================================================================
# # FuncDecl: [args*, type*]
# # node is FuncDecl
# #
# # ParamList: [params**]
# # node.args is the ParamList
# # Decl: [name, quals, storage, funcspec, type*, init*, bitsize*]
# # an item in the ParamList is a Decl   
#
# # TypeDecl: [declname, quals, type*]  
# # ndoe.type is TypeDecl  
# 
# # IdentifierType: [names]
# # ndoe.type.tpye is IdentifierType  
#
# This is used to contruct information for each function and the tracking data
#===============================================================================
class FuncDeclVisitor(c_ast.NodeVisitor):
    def visit_FuncDecl(self, node):
        global result
        result.tuple[-1].add_function()
        parse_func(node)
        
# automatically generate the tracking fields        
def construct_desc_fields(field_str):
    # construct tracking descriptor struture
    desc_str        = "desc_data"
    pdesc_str       = "parent_desc"
    desc_add_str    = "desc_data_add"
    desc_sizeof     = "size_of"
    desc_retval     = "desc_data_retval"
    if (desc_str in field_str and pdesc_str in field_str):
        idx = field_str.index(pdesc_str)
        result.tuple[-1].desc_data_fields.append([field_str[idx+1],field_str[idx+2]])
    elif (desc_str in field_str and desc_sizeof in field_str):
        idx = field_str.index(desc_sizeof)
        result.tuple[-1].desc_data_fields.append([field_str[idx+2],field_str[idx+3]])         
    elif (desc_str in field_str):
        idx = field_str.index(desc_str)
        result.tuple[-1].desc_data_fields.append([field_str[idx+1],field_str[idx+2]])            
    elif (desc_add_str in field_str):
        idx = field_str.index(desc_add_str)
        result.tuple[-1].desc_data_fields.append([field_str[idx+2].split(" ")[0],field_str[idx+1]])
    elif (desc_retval in field_str):
        idx = field_str.index(desc_retval)
        result.tuple[-1].desc_data_fields.append([field_str[idx+1],field_str[idx+2]])
           
def parse_func(node):
    global idl_parse_result 
    func_params = [] 

    ##### begin of a function #####
    fun = result.tuple[-1].functions[-1]   # last added tuple and last added functoin
    fun_info = fun.info
    #pprint (result.tuple[0].sm_info)
    for k, v in result.tuple[-1].sm_info.iteritems():
        #print(k)
        #print(v)
        #print(node.type.declname)
        #print()
        if (node.type.declname == v): 
            fun_info[fun.sm_state]  = k
        fun_info[fun.name]      = node.type.declname # set creation  or terminal func
    if not fun_info[fun.sm_state]:     # for any function that has not been set up the state, set it to "transition"
        fun_info[fun.sm_state]  = "transition"

    #### parameters of a function #####
    for param_decl in node.args.params:
        func_params = parse_parameters(param_decl)
        #print (func_params)
        #print (list(traverse(func_params)))
        # swap the type and value for para (last one is the pycparser type, eg.g, PtrDecl)
        tmp = func_params[-2]
        func_params[-2] = func_params[-3]
        func_params[-3] = tmp
           
        #print (func_params)
        construct_desc_fields(func_params)   # construct desc tracking fields    
        
        # for normal parameters
        fun.normal_para.append((func_params[-3], func_params[-2]))
           
        # if there is a match 
        if (func_params[0] in fun_info):
            if isinstance(fun_info[func_params[0]], basestring):
                print (">>>>>  " + func_params[0])
                fun_info[func_params[0]] = func_params[1:]
            elif isinstance(fun_info[func_params[0]], list):
                fun_info[func_params[0]].append(func_params[1:])
          
    #### return of a function ####        
    func_return = parse_idl_str('CD', str(get_dec_type_name(node)[0]))
    if (not func_return[0]):
        func_return[0] = node.type.type.names[0]
                
    construct_desc_fields(func_return)   # construct desc tracking fields    
    
    fun_info[func_return[0]] = func_return[1:]
    
    #print (result.tuple[-1].functions[-1].normal_para)
    #print (result.tuple[-1].functions[-1].info)

# # Decl: [name, quals, storage, funcspec, type*, init*, bitsize*]
# # node is a Decl
def parse_parameters(node):
    func_params = parse_idl_str('CD', node.name)
    if (not func_params[0]):
        func_params[0] = node.name  # normal para 
        
    param_str = get_class_name(node.type)
    if (param_str == keywords.ptrdecl):
        func_params.append(get_type_name(node)[0]+" *")
    if (param_str == keywords.typedecl):
        func_params.append(node.type.type.names[0])
    if (param_str == keywords.funcdecl):
        for param_funcdecl in node.type.args.params:
            func_params.append(param_funcdecl.name)
        sub_return = get_class_name(node.type.type)
        if (sub_return == keywords.ptrdecl):
            ret_tp = node.type.type.type.type.names
            ret_tp[0] = ret_tp[0]+" *"
        if (sub_return == keywords.typedecl):    
            ret_tp = node.type.type.type.names                    
        func_params.append(ret_tp[0])                

    func_params.append(param_str)  # add pycparser type
    #print(func_params)
    return func_params
  
#===============================================================================
# # main function - parsing the input information
#===============================================================================
def parse_func_decl(ast):
    v = FuncDeclVisitor()
    v.visit(ast)
    result.gvars["desc_data"] = result.tuple[-1].desc_data_fields
    
def parse_global_info(ast):
    v = StructVisitor()
    v.visit(ast)
    
def parse_state_machine(ast):
    global transition_list
    transition_list = []
    v = DeclVisitor()
    v.visit(ast) 
    #pprint (result.tuple[0].sm_info)
    #pprint(result.tuple[-1].sm_info['creation'])
    #pprint(result.tuple[-1].sm_info['terminal'])
    #pprint(result.tuple[-1].sm_info['transition'])
   

#===============================================================================
# def parse_global_vars(ast):
#     v = GlobalVarsVisitor()
#     v.visit(ast)
#===============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = 'cidl.h'
    
    os.system("gcc -E cidl.h -o cidl_pre");        
    #os.system("cat cidl_pre");
    
    # print_some_space() 
    # print_logo('<--- AST --->')    
    parser = c_parser.CParser()
    ast = parse_file('cidl_pre', use_cpp=True,
                     cpp_path='cpp',
                     cpp_args=r'-Iutils/fake_libc_include')
    #ast.show()
    
    result = keywords.IDLServices()
    
    parse_global_info(ast)
    parse_state_machine(ast)
    #pprint (result.tuple[0].sm_info)
    #print()    
    parse_func_decl(ast)
    #pprint(result.gvars)
#===============================================================================
#     # pprint (result.tuple[0].info)
#     # pprint (result.tuple[0].sm_info)
#     # pprint (result.tuple[0].desc_data_fields)
#     pprint (result.gvars)
# 
#     print("")
#     pprint (result.tuple[0].functions[0].info)
#     print("")
#     pprint (result.tuple[0].functions[1].info)
#     print("")
#    pprint (result.tuple[0].functions[2].info)
#     print("")
#     pprint (result.tuple[0].functions[3].info)
#     print("")
#    exit()
#===============================================================================
  
    c3_gen.idl_generate(result, ast)
    
    