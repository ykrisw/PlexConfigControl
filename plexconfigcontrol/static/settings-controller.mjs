const themes=['System','Light','Dark'];
const languages=['en','pl'];
export function createSettingsController(client,initial,render,onChanged=()=>{}) {
  let preferences={...initial},busy=false,error='',saved=false,disposed=false;
  const lifecycle=new AbortController();
  function emit(){if(!disposed)render({preferences:{...preferences},busy,error,saved});}
  emit();
  return {
    async save(name,value) {
      if(disposed||busy)return false;
      if(!((name==='theme'&&themes.includes(value))||(name==='language'&&languages.includes(value))))return false;
      if(preferences[name]===value)return true;
      busy=true;error='';saved=false;emit();
      try {
        const result=await client.updateSettings({[name]:value},lifecycle.signal);
        if(disposed)return false;
        if(!themes.includes(result.theme)||!languages.includes(result.language)||typeof result.timezone!=='string'||result[name]!==value)throw Error('Settings save could not be confirmed');
        preferences={...result};saved=true;onChanged({...preferences});
        return true;
      } catch(failure){if(!disposed)error=failure.message||'Settings could not be saved';return false;}
      finally{busy=false;emit();}
    },
    dispose(){disposed=true;lifecycle.abort();},
  };
}
