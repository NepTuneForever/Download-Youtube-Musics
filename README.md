# YouTube Music Downloader

Esse projeto nasceu de uma necessidade bem especifica: eu queria ouvir minhas musicas no carro, mas o radio dele nao le streaming, nao conecta com Spotify e eu so conseguia usar pendrive. Entao eu fiz essa aplicacao para facilitar baixar musicas e organizar tudo para jogar no pendrive.

## Funcionalidades

- Pesquisa por nome da musica no YouTube
- Exibe ate 15 resultados por busca
- Mostra titulo, canal, duracao e link do resultado selecionado
- Permite adicionar resultados pesquisados para uma lista de downloads
- Permite adicionar links diretos do YouTube para a mesma lista
- Baixa a lista em sequencia e remove automaticamente os itens concluidos
- Mantem na lista apenas os itens que falharem
- Faz tentativas automáticas extras quando uma musica falha
- Permite tentar novamente apenas as musicas com falha
- Converte tudo para MP3 usando `ffmpeg`
- Salva os arquivos em `musicas baixadas`

## Requisitos

- Python 3.10+
- Windows com `tkinter`

Instale as dependencias:

```bash
pip install -r requirements.txt
```

## Como usar

1. Entre na pasta do projeto.
2. Instale as dependencias com `pip install -r requirements.txt`.
3. Execute:

```bash
python Downloader.py
```

## Fluxo do app

1. Pesquise uma musica no YouTube.
2. Selecione um resultado e clique em `Adicionar a lista`.
3. Se quiser, cole links diretos e use `Adicionar link a lista`.
4. Quando terminar de montar a fila, clique em `Baixar musicas da lista`.
5. Os arquivos finais vao para a pasta `musicas baixadas`.

## Como funciona

- Na primeira conversao para MP3, o app baixa e extrai uma copia local do `ffmpeg` dentro da pasta `ffmpeg`.
- Cada musica baixada com sucesso sai da lista automaticamente.
- Se alguma falhar, ela permanece na lista para tentar de novo depois.
- Quando uma musica falha, o app tenta caminhos alternativos de download antes de desistir.
- Se ainda assim falhar, o item continua na lista com o ultimo erro salvo e pode ser reprocessado pelo botao de retry.
- O nome do arquivo usa o titulo do video, ajustado para ficar valido no Windows.

## Estrutura gerada em execucao

- `ffmpeg/`
- `musicas baixadas/`

## Aviso

Projeto para uso pessoal, educacional e experimental. Verifique os termos de uso do conteudo que voce baixar.

## Licenca

MIT.
