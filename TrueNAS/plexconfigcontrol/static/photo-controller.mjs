const valid=value=>value&&(value.present===false&&value.revision===null||value.present===true&&typeof value.revision==='string'&&/^[0-9a-f]{64}$/.test(value.revision));
export function createPhotoController(client,render){
  const state={present:false,revision:null,loading:false,busy:false,error:''};
  const lifecycle=new AbortController();let disposed=false,serial=0;
  const emit=()=>{if(!disposed)render({...state});};
  async function refresh(){
    if(disposed||state.busy||state.loading)return;
    const request=++serial;state.loading=true;emit();
    try{
      const result=await client.photoStatus(lifecycle.signal);
      if(disposed||request!==serial)return;
      if(!valid(result))throw Error('Invalid photo response');
      state.present=result.present;state.revision=result.revision;state.error='';
    }catch(error){if(!disposed&&request===serial){state.present=false;state.revision=null;state.error=error.message||'Photo unavailable';}}
    finally{if(!disposed&&request===serial){state.loading=false;emit();}}
  }
  async function mutate(action){
    if(disposed||state.busy||state.loading)return false;
    serial++;state.busy=true;state.error='';emit();
    try{
      const result=await action(lifecycle.signal);
      if(disposed)return false;
      if(!valid(result))throw Error('Photo change could not be confirmed');
      state.present=result.present;state.revision=result.revision;return true;
    }catch(error){if(!disposed)state.error=error.message||'Photo change could not be confirmed';return false;}
    finally{state.busy=false;emit();}
  }
  emit();void refresh();
  return{
    refresh,
    upload(file){
      if(disposed||state.busy||state.loading)return Promise.resolve(false);
      if(!file||!['image/jpeg','image/png'].includes(file.type)||!Number.isFinite(file.size)||file.size<=0||file.size>5*1024*1024){
        state.error='Choose a JPEG or PNG photo up to 5 MiB';emit();return Promise.resolve(false);
      }
      return mutate(signal=>client.uploadPhoto(file,signal));
    },
    remove(confirmed){return confirmed===true&&state.present?mutate(signal=>client.removePhoto(state.revision,signal)):Promise.resolve(false);},
    dispose(){disposed=true;serial++;lifecycle.abort();},
  };
}
