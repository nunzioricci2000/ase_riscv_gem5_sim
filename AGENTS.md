# Modifiche e conformità delle licenze

Queste istruzioni valgono per tutti i file di questo repository. Il submodule
ASE Studio è un repository autonomo: rispettare anche il suo AGENTS.md.

- Il codice originale del progetto è GPL-2.0-only. Conservare LICENSE senza
  modificarne il testo. Non convertire a GPL-2.0-or-later, GPL v3 o una licenza
  permissiva senza i necessari diritti. Le parti di terzi conservano le proprie
  licenze: non applicare automaticamente GPL a ogni file.
- Prima di modificare un file, leggere gli avvisi presenti. Conservare copyright,
  attribuzioni, esclusioni di garanzia e avvisi upstream, anche durante i merge.
- Nei file GPL modificati aggiungere un avviso evidente con data reale e breve
  descrizione, usando commenti validi nel linguaggio, per esempio:
  `Modified in the personal fork on YYYY-MM-DD: describe the change.`
  Non inventare date o autori delle modifiche precedenti. La cronologia Git e
  un changelog non sostituiscono l'avviso nel file richiesto dalla GPL v2 §2(a).
- Nei nuovi sorgenti originali usare `SPDX-License-Identifier: GPL-2.0-only`.
  Aggiungere copyright solo con titolare e anno verificati; non attribuire nuovo
  codice agli autori upstream automaticamente. Per JSON o altri formati senza
  commenti usare un file adiacente `<nome-file>.license` con gli avvisi pertinenti.
  Per Markdown sono ammessi commenti HTML.
- Non modificare manualmente bundle generati: intervenire sui sorgenti e sulla
  build, preservando i commenti legali e distribuendo gli avvisi insieme agli
  artefatti. Tenere traccia delle modifiche alla generazione nei sorgenti.
- Prima di incorporare una dipendenza o un asset, verificare la licenza della
  versione esatta e la compatibilità con GPL-2.0-only. Aggiornare THIRD_PARTY.md
  e includere i testi e gli avvisi richiesti. Se i diritti sono ignoti, non
  dichiarare il materiale GPL e non includerlo in una release finché chiariti.
- La finalità didattica non vieta usi commerciali consentiti dalla GPL. Non
  aggiungere divieti di vendita, modifica o redistribuzione. Non presentare il
  fork come approvato dagli autori originali o dall'università; i marchi e i
  loghi non ricevono automaticamente una licenza dal codice.
- Prima di distribuire seguire la checklist in DISTRIBUTION.md. Verificare
  `git diff --check` in entrambi i repository e i controlli pertinenti alla
  modifica; non dichiarare una verifica completa se restano elementi incerti.
- Non riscrivere la storia né effettuare commit, push o pubblicazioni solo per
  applicare queste regole. Conservare le modifiche dell'utente già presenti.

<!-- Modified in the personal fork on 2026-10-30: document only fork additions and link upstream for unchanged behavior. -->

## Documentazione del fork

- La documentazione locale spiega le aggiunte e le modifiche del fork. Per uso,
  funzionalità e procedure rimaste originali, linkare la documentazione upstream
  invece di copiarla; distinguere le funzionalità ereditate da quelle introdotte qui.
- Conservare attribuzioni, copyright, licenze e avvisi di garanzia anche quando
  si riduce o riorganizza la documentazione originale.
- Nel README di ASE Studio il primo contenuto visibile è il comando di installazione;
  indicare subito se gli asset necessari non sono ancora pubblicati.
- Per Studio, VERSION segue la versione upstream integrata. FORK.json identifica
  il pacchetto di funzionalità (attualmente Abate) e la sua revisione; non aumentare
  VERSION per una modifica esclusiva del fork. Vedere VERSIONING.md nel repository Studio.
