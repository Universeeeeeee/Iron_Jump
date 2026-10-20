"""Surgical experimental subclass: replace one base-call AST node only."""
import ast
import copy
import inspect
import textwrap


def transform(source):
    tree=ast.parse(textwrap.dedent(source));assert len(tree.body)==1
    fn=tree.body[0];assert isinstance(fn,ast.FunctionDef) and fn.name=='paintEvent'
    assert [a.arg for a in fn.args.args]==['self','event'] and not fn.decorator_list
    expected=ast.parse('super().paintEvent(event)').body[0]
    assert ast.dump(fn.body[0],include_attributes=False)==ast.dump(expected,include_attributes=False)
    assert sum(isinstance(n,ast.Name) and n.id=='super' for n in ast.walk(fn))==1
    tail=ast.dump(ast.Module(body=fn.body[1:],type_ignores=[]),include_attributes=False)
    changed=copy.deepcopy(tree)
    changed.body[0].body[0]=ast.copy_location(ast.parse('_diagnostic_base_paint(self,event)').body[0],fn.body[0])
    assert ast.dump(ast.Module(body=changed.body[0].body[1:],type_ignores=[]),include_attributes=False)==tail
    assert not any(isinstance(n,ast.Name) and n.id=='__class__' for n in ast.walk(changed))
    ast.fix_missing_locations(changed)
    return changed,dict(only_first_statement_changed=True,remaining_body_AST_equal=True,
        source_base_call=ast.unparse(fn.body[0]),experimental_base_call=ast.unparse(changed.body[0].body[0]))


def derive(original,bridge,filename):
    tree,audit=transform(inspect.getsource(original))
    env=dict(original.__globals__);assert '_diagnostic_base_paint' not in env
    env['_diagnostic_base_paint']=bridge
    exec(compile(tree,filename,'exec'),env)
    result=env['paintEvent'];assert not result.__code__.co_freevars
    result.__module__='diagnostic_canvas_bridge'
    result.__qualname__='BridgeCanvas.paintEvent'
    return result,ast.unparse(tree)+'\n',audit
