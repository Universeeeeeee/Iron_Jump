"""Exact value comparison; report mismatches rather than deleting output fields."""
def differences(actual,expected,limit=12):
    result=[]
    def visit(a,b,path):
        if len(result)>=limit or a==b:return
        if isinstance(a,dict) and isinstance(b,dict) and a.keys()==b.keys():
            for key in a:visit(a[key],b[key],path+'/'+str(key))
        elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            for i,(x,y) in enumerate(zip(a,b)):visit(x,y,path+'/'+str(i))
        else:result.append(dict(path=path,actual=str(a)[:160],expected=str(b)[:160]))
    visit(actual,expected,'');return result
