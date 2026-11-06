"""Conservative three-way merges for a student's single working IEP."""
import copy
import uuid


def combine(base, current, proposed, conflicts, path='', source='Earlier draft'):
    if proposed == base or proposed == current: return copy.deepcopy(current)
    if current == base: return copy.deepcopy(proposed)
    if all(isinstance(x,dict) for x in (base,current,proposed)) and base.keys()==current.keys()==proposed.keys():
        return {key:combine(base[key],current[key],proposed[key],conflicts,
                            f'{path}.{key}' if path else key,source) for key in base}
    if all(isinstance(x,list) for x in (base,current,proposed)):
        size=len(base)
        # Deletions and recognizable row moves cannot safely share positional edits.
        moved=any(value in base and base.index(value)!=i
                  for values in (current,proposed) for i,value in enumerate(values[:size]))
        if len(current)>=size and len(proposed)>=size and not moved:
            result=[combine(base[i],current[i],proposed[i],conflicts,f'{path}.{i}',source) for i in range(size)]
            for value in current[size:]+proposed[size:]:
                if value not in result: result.append(copy.deepcopy(value))
            return result
    conflicts.append({'id':uuid.uuid4().hex,'path':path,'current':copy.deepcopy(current),
                      'proposed':copy.deepcopy(proposed),'source':source})
    return copy.deepcopy(current)


def evidence_union(*groups):
    import json
    return list({json.dumps(value,sort_keys=True):copy.deepcopy(value) for group in groups for value in group}.values())
