from flask import Flask, render_template, request, jsonify, url_for, session, redirect
import json
import os
from pathlib import Path
from functools import wraps
app = Flask(__name__)
app.secret_key = 'chave-secreta-segura-2025'
# Arquivos
ARQ_VOTOS = 'votos.json'
ARQ_CONFIG = 'config.json'

# Valores padrão
PADRAO_CANDIDATOS = [
    {"nome": "Aluizo"},
    {"nome": "Andre"},
    {"nome": "Fabio"},
    {"nome": "Guilherme"},
    {"nome": "Lucas"},
    {"nome": "Michael"},
    {"nome": "Thiago O"},
    {"nome": "Thiago R"},
    {"nome": "Walisson"},
]
PADRAO_TURNOS = ['1º turno', '2º turno', '3° turno']
PADRAO_CONFIG = {
    "candidatos": PADRAO_CANDIDATOS,
    "turnos": PADRAO_TURNOS,
    "turno_atual": "1º turno",
    "presentes": 0,
    "votaram": 0
}


def ler_json_seguro(path, padrao):
    """Lê um JSON e retorna padrao se vazio ou inválido."""
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return json.loads(json.dumps(padrao))
    try:
        with open(path, 'r', encoding='utf-8') as f:
            conteudo = f.read().strip()
            if not conteudo:
                raise ValueError
            return json.loads(conteudo)
    except Exception:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return json.loads(json.dumps(padrao))


def inicializar_arquivos():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)

    # Garante que "Voto Nulo" exista no config['candidatos']
    if not any(c['nome'] == "Voto Nulo" for c in config.get("candidatos", [])):
        config.setdefault("candidatos", []).append({"nome": "Voto Nulo"})

    # Garantir turnos padrão se não existir
    config.setdefault('turnos', PADRAO_TURNOS)
    config.setdefault('turno_atual', config['turnos'][0])

    # Lê o arquivo de votos atual e detecta formato
    votos_raw = None
    if os.path.exists(ARQ_VOTOS):
        try:
            with open(ARQ_VOTOS, 'r', encoding='utf-8') as f:
                votos_raw = json.load(f)
        except Exception:
            votos_raw = None

    # Se está no formato antigo (chaves candidatos no topo), migrar para por-turno
    votos_por_turno = {}
    turnos = config.get('turnos', PADRAO_TURNOS)
    for t in turnos:
        votos_por_turno[t] = {}

    if isinstance(votos_raw, dict):
        # detectar se é formato "flat" (chaves candidatos) ou por-turno (chave de turno)
        top_keys = list(votos_raw.keys())
        # heurística simples: se alguma key coincide com um turno -> já é por-turno
        if any(k in turnos for k in top_keys):
            # já é por-turno, assegurar chaves para todos os turnos
            votos_por_turno = votos_raw
            for t in turnos:
                votos_por_turno.setdefault(t, {})
        else:
            # é flat -> migrar: colocar tudo no turno atual (ou 1º turno)
            alvo = config.get('turno_atual', turnos[0])
            for k, v in votos_raw.items():
                votos_por_turno.setdefault(alvo, {})
                votos_por_turno[alvo][k] = int(v or 0)
    else:
        # cria estrutura vazia por turno com candidatos zerados
        pass

    # garantir candidatos por turno e zerar candidatos ausentes
    # obter lista de nomes atuais (do 1º turno padrão)
    nomes_padrao = [c['nome'] for c in config.get('candidatos', [])]
    for t in turnos:
        # se não houver candidatos definidos por turno, use nomes_padrao
        if not votos_por_turno.get(t):
            votos_por_turno[t] = {n: 0 for n in nomes_padrao}
        else:
            # garante que chaves existam para os nomes atuais (evita KeyError)
            for n in nomes_padrao:
                votos_por_turno[t].setdefault(n, 0)
            # remove chaves que não são mais candidatos (opcional)
            to_remove = [k for k in votos_por_turno[t].keys() if k not in nomes_padrao]
            for k in to_remove:
                votos_por_turno[t].pop(k)

    # salva arquivos atualizados
    with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
        json.dump(votos_por_turno, f, indent=4, ensure_ascii=False)
    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

@app.route('/config_turno')
def config_turno():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    return jsonify({'turno_atual': config.get('turno_atual')})


@app.route('/')
def index():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    turno_atual = config.get('turno_atual', '1º Turno')

    # pega a lista de nomes dos candidatos desse turno
    nomes_turno = config.get('candidatos_por_turno', {}).get(turno_atual, [])

    # busca os objetos completos (com nome e foto)
    candidatos_completos = []
    for nome in nomes_turno:
        if nome == "Voto Nulo":
            candidatos_completos.append({"nome": "Voto Nulo", "foto": None})
            continue
        for c in config.get('candidatos', []):
            if c['nome'] == nome:
                candidatos_completos.append(c)
                break

    return render_template('index.html', candidatos=candidatos_completos, turno_atual=turno_atual)




@app.route('/votar', methods=['POST'])
def votar():
    """Recebe JSON: { "votos": ["Nome1","Nome2", ...] }"""
    dados = request.get_json(force=True)
    votos_recebidos = dados.get('votos', [])
    if not isinstance(votos_recebidos, list) or len(votos_recebidos) == 0:
        return jsonify({'mensagem': 'Nenhum voto recebido!'}), 400
    if len(votos_recebidos) > 6:
        return jsonify({'mensagem': 'Você só pode votar em até 6 candidatos!'}), 400

    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    turnos = config.get('turnos', PADRAO_TURNOS)
    turno_atual = config.get('turno_atual', turnos[0])

    # lê votos por turno (estrutura esperada: { "1º turno": {cand: qtd}, "2º turno": {...} })
    votos_por_turno = ler_json_seguro(ARQ_VOTOS, {t: {} for t in turnos})
    votos_por_turno.setdefault(turno_atual, {})

    candidatos_validos = []
    # tenta obter candidatos do turno atual (se existir config['candidatos_por_turno'])
    candidatos_por_turno = config.get('candidatos_por_turno', {})
    if candidatos_por_turno and candidatos_por_turno.get(turno_atual):
        candidatos_validos = candidatos_por_turno[turno_atual]
    else:
        # fallback para config['candidatos']
        candidatos_validos = [c['nome'] for c in config.get('candidatos', [])]

    # garante chaves no dicionário do turno atual
    for nome in candidatos_validos:
        votos_por_turno[turno_atual].setdefault(nome, 0)

    invalidados = []
    for v in votos_recebidos:
        if v in votos_por_turno[turno_atual]:
            votos_por_turno[turno_atual][v] += 1
        else:
            invalidados.append(v)

    # atualiza contador de quem já votou (global; se preferir pode fazer por-turno)
    config['votaram'] = config.get('votaram', 0) + 1

    # salva
    with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
        json.dump(votos_por_turno, f, indent=4, ensure_ascii=False)
    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    msg = f'Votos confirmados: {", ".join([v for v in votos_recebidos if v not in invalidados])}'
    if invalidados:
        msg += f' (ignorados: {", ".join(invalidados)})'
    return jsonify({'mensagem': msg})



@app.route('/resultados', methods=['GET'])
def resultados():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    turnos = config.get('turnos', PADRAO_TURNOS)
    turno_atual = config.get('turno_atual', turnos[0])

    votos_por_turno = ler_json_seguro(ARQ_VOTOS, {t: {} for t in turnos})
    votos_do_turno = votos_por_turno.get(turno_atual, {})

    return jsonify({
        'turno_atual': turno_atual,
        'votos': votos_do_turno,
        'todos_turnos': votos_por_turno  # opcional, para debug
    })


# Decorador para exigir login
def login_obrigatorio(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if not session.get('logado'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorada
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        senha = request.form['senha']

        if usuario == 'jardim2025' and senha == '02022019':
            session['logado'] = True
            return redirect(url_for('admin_page'))
        else:
            return render_template('login.html', erro="Usuário ou senha incorretos.")
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@login_obrigatorio
def admin_page():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    return render_template('admin.html', config=config)


@app.route('/admin/data')
def admin_data():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    votos_por_turno = ler_json_seguro(ARQ_VOTOS, {t: {} for t in config.get('turnos', ["1º Turno","2º Turno","3º Turno"])})

    turno_atual = config.get('turno_atual', config.get('turnos', ["1º Turno"])[0])
    candidatos_do_turno = config.get('candidatos_por_turno', {}).get(turno_atual, [])
    votos_do_turno = votos_por_turno.get(turno_atual, {c: 0 for c in candidatos_do_turno})

    presentes = config.get('presentes', 0)
    votaram = config.get('votaram', 0)
    faltam = max(0, presentes - votaram)

    # calcula percentuais (com base nos presentes)
    percent = {}
    for c in candidatos_do_turno:
        percent[c] = round((votos_do_turno.get(c, 0) / presentes * 100) if presentes else 0, 2)

    resp = {
        'presentes': presentes,
        'votaram': votaram,
        'faltam': faltam,
        'turno_atual': turno_atual,
        'turnos': config.get('turnos', []),
        'candidatos': candidatos_do_turno,
        'votos': votos_do_turno,
        'percent': percent,
        'candidatos_por_turno': config.get('candidatos_por_turno', {})
    }
    return jsonify(resp)



@app.route('/admin/update_config', methods=['POST'])
def admin_update_config():
    dados = request.get_json(force=True)
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)

    # --- Inicializa 3 turnos fixos ---
    turnos_padrao = ["1º Turno", "2º Turno", "3º Turno"]
    config.setdefault('turnos', turnos_padrao)
    config.setdefault('turno_atual', turnos_padrao[0])

    # --- Garantir estrutura candidatos_por_turno no config ---
    config.setdefault('candidatos_por_turno', {})
    # Se não existir, popula 1º turno com config['candidatos'] (se houver) ou vazio
    if not config['candidatos_por_turno'].get(turnos_padrao[0]):
        if config.get('candidatos'):
            config['candidatos_por_turno'][turnos_padrao[0]] = [c['nome'] for c in config['candidatos']]
        else:
            config['candidatos_por_turno'][turnos_padrao[0]] = [n for n in PADRAO_CANDIDATOS] if 'PADRAO_CANDIDATOS' in globals() else []

    for t in turnos_padrao:
        config['candidatos_por_turno'].setdefault(t, [])

    # Lê votos organizados por turno
    votos_por_turno = ler_json_seguro(ARQ_VOTOS, {t: {} for t in turnos_padrao})
    for t in turnos_padrao:
        votos_por_turno.setdefault(t, {})

    # Garante que todos os candidatos existam nas contagens de votos (para o turno atual)
    turno_atual = config['turno_atual']
    nomes_turno_atual = config['candidatos_por_turno'].get(turno_atual, [])
    for n in nomes_turno_atual:
        votos_por_turno[turno_atual].setdefault(n, 0)

    # --- Atualiza presentes ---
    if 'presentes' in dados:
        try:
            config['presentes'] = int(dados['presentes'])
        except Exception:
            pass

    # --- Atualiza turnos se fornecido (mantém padrão se vazio) ---
    if 'turnos_text' in dados:
        turnos = [t.strip() for t in dados['turnos_text'].split(',') if t.strip()]
        if turnos:
            config['turnos'] = turnos
            # garante candidatos_por_turno para cada novo turno
            for t in turnos:
                config['candidatos_por_turno'].setdefault(t, [])
            if config.get('turno_atual') not in turnos:
                config['turno_atual'] = turnos[0]

    # --- Atualiza turno atual ---
    if 'turno_atual' in dados:
        turno_selecionado = dados['turno_atual']
        if turno_selecionado in config.get('turnos', []):
            config['turno_atual'] = turno_selecionado

    # --- Atualiza candidatos ---
    # Fluxo: se receber candidatos_text + campo turno_for_candidates -> atualiza apenas esse turno.
    # Se receber apenas candidatos_text sem turno_for_candidates, trata como "candidatos do 1º turno / padrão".
    if 'candidatos_text' in dados:
        texto = dados['candidatos_text']
        lista = [c.strip() for c in texto.split(',') if c.strip()]
        # garante "Voto Nulo"
        if not any(x.lower() == "voto nulo" for x in lista):
            lista.append("Voto Nulo")
        # determina qual turno atualizar
        alvo = dados.get('turno_for_candidates') or config.get('turno_atual') or turnos_padrao[0]
        # atualiza candidatos do turno alvo
        config['candidatos_por_turno'][alvo] = lista

    # --- Resetar votos (zera todos os turnos) ---
    if dados.get('reset_votos'):
        for turno in config['turnos']:
            candidatos = config['candidatos_por_turno'].get(turno, [])
            votos_por_turno[turno] = {c: 0 for c in candidatos}
        config['votaram'] = 0

    # --- Salva alterações ---
    with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
        json.dump(votos_por_turno, f, indent=4, ensure_ascii=False)
    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    return jsonify({'mensagem': 'Configurações atualizadas com sucesso.'})



if __name__ == '__main__':
    inicializar_arquivos()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

