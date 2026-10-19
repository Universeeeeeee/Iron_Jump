"""Only retain original block clock endpoints; no extra timer calls."""
import ast
import copy
import inspect
import textwrap

def transform(source):
    tree=ast.parse(textwrap.dedent(source));original=copy.deepcopy(tree);function=tree.body[0];added=0
    for node in ast.walk(function):
        if isinstance(node,ast.For) and isinstance(node.target,ast.Tuple) and [x.id for x in node.target.elts if isinstance(x,ast.Name)]==['block','ops']:
            node.body.insert(1,ast.parse('span_start = wall').body[0]);added+=1
    for node in ast.walk(function):
        if isinstance(node,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='thread_cpu_ns' for k in node.keys):
            node.keys.extend([ast.Constant('wall_begin_ns'),ast.Constant('wall_end_ns')]);node.values.extend([ast.Name('span_start',ast.Load()),ast.parse('span_start + wall',mode='eval').body]);added+=1
    assert added==2
    # Remove exactly the two additions; original method body must remain identical.
    back=copy.deepcopy(tree)
    for node in ast.walk(back):
        if isinstance(node,ast.For):node.body=[x for x in node.body if not (isinstance(x,ast.Assign) and isinstance(x.targets[0],ast.Name) and x.targets[0].id=='span_start')]
        if isinstance(node,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='wall_begin_ns' for k in node.keys):node.keys=node.keys[:-2];node.values=node.values[:-2]
    assert ast.dump(back,include_attributes=False)==ast.dump(original,include_attributes=False)
    return ast.fix_missing_locations(tree)

def instrument(replay):
    env=dict(replay.__dict__);tree=transform(inspect.getsource(replay.Trial.measure));exec(compile(tree,'diagnostic_block_endpoints','exec'),env);return env['measure']
