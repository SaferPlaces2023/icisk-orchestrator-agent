import os
import re
import copy

import nbformat as nbf



class CellMetadata():
    
    NEED_FORMAT = "NEED_FORMAT"             # DOC: will use a dict to format the cell — (Default set to False)
    CHECK_IMPORT = "CHECK_IMPORT"           # DOC: will check if the imports are already in the notebook and discard them — (Default set to False)
    CHECK_EXISTENCE = "CHECK_EXISTENCE"     # DOC: will check if the cell already exists in the notebook and discard it — (Default set to Fal)
    MODE = "MODE"                           # DOC: will use the cell based on the mode attribute of the tool — (Default is unset)
    

def notebook_copy(notebook: nbf.NotebookNode) -> nbf.NotebookNode:
    return copy.deepcopy(notebook)   
 

def write_notebook_template(notebook: nbf.NotebookNode, values_dict: dict = dict(), mode = None) -> nbf.NotebookNode:
    
    def safe_code_lines(code: str, format_dict: dict = None) -> str:
        if format_dict is not None:
            code = code.format(**format_dict)
        lines = code.split('\n')
        if len(lines) > 0:
            while lines[0] == '':
                lines = lines[1:]
            while lines[-1] == '':
                lines = lines[:-1]
            spaces = re.match(r'^\s*', lines[0])
            spaces = len(spaces.group()) if spaces else 0
            lines = [line[spaces:] for line in lines]
            lines = [f'{line}\n' if idx!=len(lines)-1 else f'{line}' for idx,line in enumerate(lines)]
        code = ''.join(lines)
        return code
    
    def necessary_imports(code: str | list[str], context_code: str | list[str] = None):
            lines = code if type(code) is list else [code]
            context_code = context_code if type(context_code) is list else [context_code] if context_code is not None else []
            lines = [ l for l in lines if l.strip() not in context_code ]
            return '\n'.join(lines)
    
    def compile_cell(cell):
        cell.source = safe_code_lines(cell.source, format_dict=values_dict if cell.metadata.get(CellMetadata.NEED_FORMAT, False) else None)
        if cell.metadata.get(CellMetadata.NEED_FORMAT, False):
            cell.metadata.pop(CellMetadata.NEED_FORMAT, None)
        if cell.metadata.get(CellMetadata.CHECK_IMPORT, False):
            previous_import_code = '\n'.join([c.source for c in notebook.cells[:ic] if c.metadata.get(CellMetadata.CHECK_IMPORT, False)])
            cell.source = necessary_imports(cell.source, context_code=previous_import_code)
        if cell.metadata.get(CellMetadata.CHECK_EXISTENCE, False):
            if any([cell.source == pc.source for pc in notebook.cells[:ic]]):
                cell.source = ""
        return cell
    
    compiled_cells = []
    for ic,cell in enumerate(notebook.cells):
        if mode is None:
            cell = compile_cell(cell)
        elif cell.metadata.get(CellMetadata.MODE, None) is None or cell.metadata.get(CellMetadata.MODE, None) == mode:
            cell = compile_cell(cell)
        else:
            continue
        compiled_cells.append(cell)
       
    notebook.cells = [cell for cell in compiled_cells if cell.cell_type != "code" or cell.source.replace('\n', '').strip() != ""]     
    
    return notebook        