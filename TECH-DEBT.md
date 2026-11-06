# Technical debt

Ogni voce di debito tecnico è un file separato in [`tech-debt/`](tech-debt/), con nome
`<slug-breve>.md` e come contenuto una sola voce (area interessata, problema concreto,
esito desiderato).

- **Aggiungere una voce:** creare un nuovo file in `tech-debt/`.
- **Risolvere una voce:** eliminare il suo file nella stessa PR del fix.
- **Non modificare questo file** e non mettere più voci nello stesso file: due PR che toccano
  file diversi non vanno mai in conflitto fra loro (con un unico elenco, ogni PR che rimuove
  una voce adiacente a un'altra confligge con le altre).
