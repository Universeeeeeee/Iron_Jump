"""Only union non-threaded DPC/ISR time; keep threaded DPC separate."""
def union(intervals):
    out=[]
    for a,b in sorted(intervals):
        assert a<=b
        if out and a<=out[-1][1]:out[-1]=(out[-1][0],max(b,out[-1][1]))
        else:out.append((a,b))
    return out

def overlap(a,b):
    return sum(max(0,min(y,v)-max(x,u)) for x,y in union(a) for u,v in union(b))
