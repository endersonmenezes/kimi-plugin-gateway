#!/bin/sh
# Prova do Gateway: se qualquer etapa executasse código upstream, este
# script criaria o arquivo-marca ao lado dele. A suíte confirma que o
# marca nunca existe após conversão, validação e empacotamento.
echo "codigo upstream executado" > "$(dirname "$0")/MARCA-EXECUTADO.txt"
