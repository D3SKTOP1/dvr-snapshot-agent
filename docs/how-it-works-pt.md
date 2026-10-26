DVR Agent CAMAI — Descrição da Aplicação
O que é
DVR Agent CAMAI é um sistema de captura automática de imagens de câmeras conectadas a DVRs Intelbras (linha MHDX). O agente conecta ao DVR pela rede local, captura snapshots JPEG de cada câmera configurada e armazena localmente no disco ou envia para uma API na nuvem.

Componentes
Arquivo	Função
dvr_monitor.exe	Painel visual com log em tempo real, configurações e controle do agente
dvr_agent.exe	Agente headless (roda em segundo plano como serviço do Windows)
config.json	Arquivo de configuração editável
Funcionalidades
Captura periódica de frames JPEG via HTTP Digest Auth do DVR
Dois modos de armazenamento:
Local — salva arquivos .jpg em pasta do Windows (ex: D:\INJECTION\cam01\)
VPS / API — envia as imagens em Base64 para uma API de ingestão com chave de autenticação
Detecção de movimento — consulta o endpoint CGI de alarme do DVR antes de capturar; só salva frame quando há movimento real na câmera
Intervalo configurável — captura a cada N segundos (modo normal) ou verifica alarme a cada N segundos (modo movimento)
Painel de monitoramento com:
Tabela de câmeras com status, tamanho do arquivo e latência em tempo real
Log colorido com histórico de capturas e erros
Botão Iniciar / Pausar o agente
Acesso direto à pasta de imagens
Configurações pelo painel — IP, porta, usuário, senha, intervalo, modo de armazenamento, câmeras e detecção de movimento, tudo sem editar o JSON manualmente
Diagnóstico de alarme — botão "Testar alarme" mostra a resposta bruta do CGI do DVR para identificar problemas de conectividade
Serviço automático — registrado no Agendador de Tarefas do Windows, inicia com o sistema e reinicia automaticamente se travar
Instalação
Execute DVRAgent-Setup-1.0.0.exe
Siga o assistente (instalação em %LOCALAPPDATA%\DVR Agent CAMAI, sem necessidade de administrador)
Ao final, marque "Abrir DVR Monitor agora"
O serviço DVRAgent é registrado e iniciado automaticamente
Configuração inicial
Abra o monitor → clique em ⚙ Configurações e preencha:

DVR IP        →  IP do DVR na rede local (ex: 192.168.1.100)
Porta HTTP    →  80 (padrão Intelbras)
Usuário       →  admin
Senha         →  senha do DVR
Intervalo (s) →  frequência de captura em segundos
Armazenamento:

Local (disco) → informe o caminho (ex: D:\INJECTION)
VPS / API → informe a URL e a chave da API
Câmeras: adicione uma linha por câmera com cam_id, número do canal e nome da zona.

Clique em Testar conexão para validar antes de salvar.

Detecção de movimento
No DVR: Menu → Configurar → Evento → Detectar → Movimento → ative por canal e configure as zonas
No monitor: ⚙ Configurações → marque "Capturar somente com movimento detectado"
Defina o intervalo de verificação (padrão: 2 segundos)
Clique em Testar alarme para confirmar que o DVR está respondendo ao CGI
Quando ativo, o log exibe:

▲ MOVIMENTO — frame capturado
– sem mov. — câmera sem movimento, snapshot ignorado
Gerenciamento do serviço
Via menu Iniciar → DVR Agent CAMAI:

Atalho	Ação
Iniciar serviço	Inicia o dvr_agent.exe em segundo plano
Parar serviço	Para o agente
Configurar	Abre o config.json no Bloco de Notas
DVR Monitor	Abre o painel visual
Ou pelo PowerShell:

.\manage.ps1 start    # inicia
.\manage.ps1 stop     # para
.\manage.ps1 status   # exibe estado atual
.\manage.ps1 logs     # exibe últimas capturas
Estrutura de arquivos gerados
D:\INJECTION\
  cam01\
    cam01_20260428_104500.jpg
    cam01_20260428_104530.jpg
  cam02\
    cam02_20260428_104500.jpg
