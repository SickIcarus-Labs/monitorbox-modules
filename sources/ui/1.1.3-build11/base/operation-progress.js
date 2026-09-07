'use strict';

const baseShowOperation=showOperation;

function canaryProgressText(snapshot){
  const status=snapshot?.status,run=status?.run;
  if(!run?.running)return'';
  const current=run.current_database||run.current?.database||run.current?.name;
  const completed=run.completed_databases||run.completed||[];
  const pending=run.pending_databases||run.pending||[];
  const bits=[];
  if(current)bits.push(`DB Canary: ${current}`);
  if(Array.isArray(completed)||Array.isArray(pending)){
    const done=Array.isArray(completed)?completed.length:0,total=done+(Array.isArray(pending)?pending.length:0)+(current?1:0);
    if(total)bits.push(`${done}/${total} databases complete`);
  }
  return bits.join(' · ');
}

showOperation=function(){
  baseShowOperation();
  const operation=app.operation;if(!operation)return;
  const progress=operation.progress||{},completed=Number(progress.completed_sources||0),total=Number(progress.total_sources||operation.expected_sources||0);
  const canary=canaryProgressText(operation.db_canary_progress);
  const sourceText=total?`${completed}/${total} monitoring source${total===1?'':'s'} complete`:'Fresh monitoring pass running';
  $('#operation-copy').textContent=canary?`${sourceText} · ${canary}`:sourceText;
  const percent=total?Math.max(3,Math.min(100,completed/total*100)):8;
  $('#operation-progress').style.width=`${percent}%`;
};
