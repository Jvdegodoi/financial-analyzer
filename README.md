# Financial Analyzer

Aplicativo de finanças pessoais de um casal, em Python e Streamlit. Lê os extratos em CSV de três bancos (Nubank, C6 e Inter), categoriza cada lançamento, reconhece as transferências entre as contas do próprio casal, para que não contem como receita nem como despesa, e responde a perguntas de renda e de gasto: quanto entrou e de quem, quanto saiu e para onde.

Roda no computador de quem usa e guarda o estado em arquivos JSON, sem banco de dados.

## Quem fez o quê

Eu decido o desenho, o que o app faz, as regras de produto e se cada etapa é aceita. O código e os testes foram escritos pelo Claude Code, um agente de IA, a partir de planos desenvolvidos em conjunto e escritos pelo Claude. O Code produz relatórios de tudo que fez, e eles são lidos e revisados a fim de entender se o plano foi cumprido. Não escrevi o código à mão. A ideia deste repositório é mostrar o resultado de como eu conduzo a IA: planejamento antes, testes e verificações durante e conferência depois.

## Os dados são de demonstração

O app abre num conjunto de demonstração gerado por `demonstracao/gerar.py`: 36
extratos de quatro contas, ao longo de 14 meses, com pessoas, contas e
comerciantes inventados. Os extratos de demonstração seguem o formato de exportação de cada banco e são importados pelo mesmo caminho dos extratos reais. As fixtures dos testes também são inventadas.

Este repositório é derivado de um repositório de trabalho privado: recebe só o que está numa lista de arquivos permitidos, depois de uma varredura que procura nomes, contas e documentos reais. Por isso alguns comentários citam arquivos que não vieram, como o `CLAUDE.md`, a pasta `docs/` e os testes de integração sobre o dado real.

## Como rodar

Testado no Windows, com Python 3.14.

```powershell
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\venv\Scripts\python.exe -m streamlit run app.py
```

Sem configuração, o app abre no conjunto de demonstração, montado numa pasta temporária a cada subida, com 01/11/2026 no lugar de hoje. Ele só aceita conexão do próprio computador (`localhost`).

## Testes

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest tests/ -q
```

São duas camadas. `tests/unidade/` usa fixtures sintéticas que reproduzem as manhas de byte de cada banco: o BOM e o CRLF do C6, o LF do Nubank e do Inter. `tests/demonstracao/` roda o pipeline inteiro e o app sobre o conjunto fictício
e confere os números contra os que o gerador calculou por outro caminho.

## Três regras do produto

- Transferência entre as contas do casal sem a outra metade fica pendente e conta nas métricas: o app não a neutraliza só porque o nome na descrição lembra alguém da família.
- A fonte de cada receita é atribuída à mão, transação a transação; o app não adivinha por apelido, descrição ou valor.
- A taxa de poupança pode ser negativa: o mês em que saiu mais do que entrou aparece como é.

## Defeitos conhecidos

Estão registrados, e alguns seguem abertos. Três dos que aparecem na tela: depois de confirmar uma importação, a tela volta ao preview e mostra como duplicatas as transações que acabaram de entrar; o botão "Limpar Todas as Transações" não apaga nada; e clicar no título da coluna Data ordena as datas como texto, pelo dia, e não em ordem cronológica.

## Licença

Sem licença: todos os direitos reservados. Este repositório não oferece licença de uso.