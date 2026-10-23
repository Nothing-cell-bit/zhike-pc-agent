"""Host registry for OpenDesign's planning loop; only design proposal is exposed."""
from ._contract import ToolContext
from .propose_design_spec import propose_design_spec


def propose_and_finish(args,*,ctx):
    result=propose_design_spec(args,ctx=ctx)
    if result.status=='ok':ctx.state['finalized']=True
    return result


TOOL_HANDLERS={'propose_design_spec':propose_and_finish}
TOOL_SCHEMAS=[{'name':'propose_design_spec','description':'提交完整的海报设计方案，通过校验后结束设计规划。',
    'input_schema':{'type':'object','properties':{'design_spec':{'type':'object','properties':{
        'brief':{'type':'string'},'artifact_type':{'type':'string','enum':['poster']},
        'canvas':{'type':'object','properties':{'w_px':{'type':'integer'},'h_px':{'type':'integer'}},'required':['w_px','h_px']},
        'palette':{'type':'array','items':{'type':'string'}},'typography':{'type':'object','additionalProperties':{'type':'string'}},
        'mood':{'type':'array','items':{'type':'string'}},'composition_notes':{'type':'string'},
        'layer_graph':{'type':'array','items':{'type':'object','properties':{
            'layer_id':{'type':'string'},'name':{'type':'string'},'kind':{'type':'string','enum':['background','text','brand_asset']},
            'z_index':{'type':'integer'},'text':{'type':'string'},'prompt':{'type':'string'}},'required':['layer_id','name','kind','z_index']}}
    },'required':['brief','artifact_type','canvas','layer_graph']}},'required':['design_spec']}}]
