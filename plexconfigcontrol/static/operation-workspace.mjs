// A failed status read must not reopen archives during an operation.
export function mountOperationWorkspace(root, archiveCard, signal) {
  const panel = root.querySelector('.pcc-operation-workspace');
  const back = panel.querySelector('[data-return-to-archives]');
  let locked = false;
  let resultKey = '';
  let dismissed = '';

  function update() {
    const visible = locked || Boolean(resultKey && resultKey !== dismissed);
    panel.hidden = !visible;
    archiveCard.hidden = visible;
    back.hidden = locked || !visible;
  }

  back.addEventListener('click', () => {
    dismissed = resultKey;
    update();
    root.querySelector('[data-refresh],[data-restore-action=refresh]').focus();
  }, {signal});

  return ({active, snapshot, result}) => {
    if (active || snapshot) locked = active;
    if (active) dismissed = '';
    resultKey = result ? JSON.stringify([snapshot?.execution?.request_id, snapshot?.progress?.started, result]) : '';
    update();
    return locked;
  };
}

export function activeExecution(snapshot, kind) {
  return snapshot?.execution?.kind === kind && ['QUEUED', 'RUNNING'].includes(snapshot.execution.state);
}

export function mountStageProgress(meter, kind, language) {
  const bar = meter.querySelector('progress'), percent = meter.querySelector('[data-stage-percent]');
  const format = new Intl.NumberFormat(language === 'pl' ? 'pl-PL' : 'en-GB',
    {style:'percent', maximumFractionDigits:1});
  return (visible, stage) => {
    const measured = stage?.operation === kind && stage.active === true && Number.isFinite(stage.stage_percent);
    meter.hidden = !visible;
    if (measured) bar.value = stage.stage_percent;
    else bar.removeAttribute('value');
    percent.hidden = !measured;
    percent.textContent = measured ? format.format(stage.stage_percent / 100) : '';
  };
}
