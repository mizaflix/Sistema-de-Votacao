import os
import json
from flask import Flask, render_template, request, jsonify, url_for, session, redirect, flash
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, OperationalError
from datetime import datetime
import logging

# --- Configuração da Aplicação ---
app = Flask(__name__)

# Configuração de Logging (para vermos os erros no Render)
logging.basicConfig(level=logging.INFO)

# --- Configuração do Banco de Dados (PostgreSQL) ---
# O Render irá fornecer esta URL automaticamente através das Variáveis de Ambiente
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logging.warning("DATABASE_URL não definida. A usar um SQLite local (apenas para teste).")
    # Fallback para um SQLite local se não estiver no Render (para testes locais)
    DATABASE_URL = "sqlite:///votacao_local.db"
else:
    # Garante que o SQLAlchemy entenda a URL do Render/Heroku
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave-secreta-padrao-para-testes-locais')

db = SQLAlchemy(app)

# --- Definição dos Modelos do Banco de Dados (Tabelas) ---

class Config(db.Model):
    """ Tabela para guardar a configuração (substitui config.json) """
    __tablename__ = 'config'
    # Usamos 'key' e 'value' para guardar configurações como "turno_atual": "1º Turno"
    key = db.Column(db.String(100), primary_key=True)
    # Guardamos valores complexos (como listas) como JSON string
    value = db.Column(db.Text, nullable=False)

class Eleitor(db.Model):
    """ Tabela para guardar os eleitores (substitui eleitores.json) """
    __tablename__ = 'eleitores'
    cpf = db.Column(db.String(20), primary_key=True)
    # Guarda um JSON string como: {"1º Turno": true, "2º Turno": false}
    votou_turnos = db.Column(db.Text, nullable=False, default='{}')

class Voto(db.Model):
    """ Tabela para guardar cada voto individual (substitui votos.db) """
    __tablename__ = 'votos'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cpf = db.Column(db.String(20), db.ForeignKey('eleitores.cpf'), nullable=False)
    turno = db.Column(db.String(100), nullable=False)
    candidato = db.Column(db.String(255), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Define um índice para acelerar as consultas de verificação de voto
    __table_args__ = (
        db.Index('idx_cpf_turno', 'cpf', 'turno'),
    )

# --- Valores Padrão (Usados apenas na primeira inicialização) ---
PADRAO_CANDIDATOS = [
    {"nome": "Enzo", "foto": "enzo.png"},
    {"nome": "Fabrício", "foto": "fabricio.png"},
    {"nome": "Hélio", "foto": "helio.png"},
    {"nome": "Cláudio", "foto": "claudio.png"},
    {"nome": "Marcelo", "foto": "marcelo.png"},
    {"nome": "Voto Nulo", "foto": None}
]
PADRAO_TURNOS = ['1º turno', '2º turno', '3° turno']
PADRAO_CONFIG_INICIAL = {
    "candidatos": json.dumps(PADRAO_CANDIDATOS),
    "turnos": json.dumps(PADRAO_TURNOS),
    "turno_atual": "1º turno",
    "candidatos_por_turno": json.dumps({
        "1º turno": [c['nome'] for c in PADRAO_CANDIDATOS],
        "2º turno": ["Voto Nulo"],
        "3° turno": ["Voto Nulo"]
    }),
    "presentes": "0", # Guardamos como string
    "votaram": "0"    # Guardamos como string
}

# --- Funções Auxiliares do Banco de Dados ---

def db_inicializar():
    """
    Cria as tabelas se não existirem e popula a configuração padrão.
    """
    try:
        with app.app_context():
            db.create_all()
            
            # Verifica se a configuração já foi inicializada
            config_check = Config.query.filter_by(key='turno_atual').first()
            if config_check is None:
                app.logger.info("Base de dados vazia. A inicializar configurações padrão...")
                # Popula a configuração padrão
                for key, value in PADRAO_CONFIG_INICIAL.items():
                    db.session.add(Config(key=key, value=value))
                
                db.session.commit()
                app.logger.info("Configurações padrão salvas.")
            else:
                app.logger.info("Base de dados já inicializada.")
                
    except OperationalError as e:
        app.logger.error(f"Erro operacional ao ligar/inicializar DB (verifique a DATABASE_URL): {e}")
    except Exception as e:
        app.logger.error(f"Erro inesperado ao inicializar DB: {e}")
        db.session.rollback()


def db_get_config_all():
    """
    Lê toda a configuração da tabela 'config' e retorna um dicionário.
    Faz o parse de JSON strings para listas/dicionários Python.
    """
    config_db = Config.query.all()
    config = {}
    for item in config_db:
        # Tenta fazer parse de JSON
        try:
            config[item.key] = json.loads(item.value)
        except json.JSONDecodeError:
            # Se não for JSON (ex: "1º turno"), guarda o valor string
            config[item.key] = item.value
    
    # Garante que as chaves JSON padrão existam
    config.setdefault('candidatos', [])
    config.setdefault('turnos', PADRAO_TURNOS)
    config.setdefault('candidatos_por_turno', {})
    config.setdefault('presentes', 0)
    config.setdefault('votaram', 0)
    
    return config

def db_set_config(key, value):
    """
    Atualiza ou insere uma chave de configuração.
    Converte listas/dicionários Python para JSON string antes de salvar.
    """
    if isinstance(value, (dict, list)):
        value_str = json.dumps(value, ensure_ascii=False)
    else:
        value_str = str(value)
        
    item = Config.query.filter_by(key=key).first()
    if item:
        item.value = value_str
    else:
        item = Config(key=key, value=value_str)
        db.session.add(item)
    
    # Commit é feito na rota principal para agrupar operações
    
def db_carregar_eleitores_dict():
    """
    Lê a tabela 'eleitores' e retorna um dicionário como o JSON antigo.
    { "cpf123": {"votou_turnos": {"1º turno": true}}, ... }
    """
    eleitores_db = Eleitor.query.all()
    eleitores_dict = {}
    for eleitor in eleitores_db:
        try:
            votou_turnos = json.loads(eleitor.votou_turnos)
        except json.JSONDecodeError:
            votou_turnos = {}
        eleitores_dict[eleitor.cpf] = {"votou_turnos": votou_turnos}
    return eleitores_dict

# --- Rotas da Aplicação ---

@app.route('/config_turno')
def config_turno():
    """ Rota que retorna apenas info de turno (útil para front sem recarregar) """
    turno_atual = Config.query.filter_by(key='turno_atual').first()
    return jsonify({'turno_atual': turno_atual.value if turno_atual else '1º turno'})

@app.route('/cpf', methods=['GET'])
def tela_cpf():
    """ Tela de CPF (entrada) """
    return render_template('cpf.html') if os.path.exists('templates/cpf.html') else render_template('index.html')

@app.route('/')
def index():
    """ Página principal de votação """
    if 'cpf' not in session:
        return redirect(url_for('tela_cpf'))
        
    try:
        config = db_get_config_all()
        turno_atual = config.get('turno_atual', '1º turno')
        nomes_turno = config.get('candidatos_por_turno', {}).get(turno_atual, [])
        lista_principal = config.get('candidatos', [])

        candidatos_completos = []
        for nome in nomes_turno:
            encontrado = False
            # Procura na lista principal (ignorando maiúsculas/minúsculas)
            for c in lista_principal:
                if c['nome'].lower() == nome.lower():
                    candidatos_completos.append(c)
                    encontrado = True
                    break
            
            if not encontrado:
                # Adiciona mesmo se não estiver na lista principal (ex: Voto Nulo)
                candidatos_completos.append({"nome": nome, "foto": None})
        
        return render_template('index.html', candidatos=candidatos_completos, turno_atual=turno_atual)
    
    except Exception as e:
        app.logger.error(f"Erro na rota /: {e}")
        # Se a DB falhar (ex: na inicialização), mostra um erro amigável
        return "Erro ao carregar a configuração da votação. Verifique os logs.", 500


@app.route('/verificar_cpf', methods=['POST'])
def verificar_cpf():
    """ Verifica se o CPF existe e se já votou neste turno """
    dados = request.get_json(force=True)
    cpf = dados.get('cpf', '').strip()
    if not cpf:
        return jsonify({'erro': 'CPF inválido.'}), 400

    eleitor = Eleitor.query.filter_by(cpf=cpf).first()
    if not eleitor:
        return jsonify({'erro': 'CPF não cadastrado.'}), 400

    config_turno = Config.query.filter_by(key='turno_atual').first()
    turno_atual = config_turno.value if config_turno else '1º turno'

    # Verifica se já votou (no banco de dados)
    # Esta verificação é mais segura que a do eleitor.votou_turnos
    voto_existente = Voto.query.filter_by(cpf=cpf, turno=turno_atual).first()
    if voto_existente:
        return jsonify({'erro': 'Este CPF já votou neste turno!'}), 400
        
    # Verifica também a coluna 'votou_turnos' do eleitor (redundância)
    try:
        votou_turnos = json.loads(eleitor.votou_turnos)
        if votou_turnos.get(turno_atual, False):
            return jsonify({'erro': 'Este CPF já votou neste turno!'}), 400
    except json.JSONDecodeError:
        pass # Ignora se o JSON estiver mal formatado

    session['cpf'] = cpf
    session['turno_atual'] = turno_atual
    return jsonify({'ok': True, 'turno_atual': turno_atual})

@app.route('/votar', methods=['POST'])
def votar():
    """ Regista os votos no banco de dados """
    dados = request.get_json(force=True)
    votos_recebidos = dados.get('votos', [])
    
    if not votos_recebidos or len(votos_recebidos) > 4:
        return jsonify({'mensagem': 'Seleção de votos inválida (mínimo 1, máximo 4).'}), 400
    cpf = session.get('cpf')
    turno = session.get('turno_atual')

    if not cpf or not turno:
        return jsonify({"mensagem": "Sessão expirada. Faça login novamente."}), 403

    try:
        # --- TRANSAÇÃO DE VOTO (Resolve "Race Condition") ---
        # 1. Verifica MAIS UMA VEZ se já votou (segurança máxima)
        voto_existente = Voto.query.filter_by(cpf=cpf, turno=turno).first()
        if voto_existente:
            return jsonify({"mensagem": "Voto duplicado detetado."}), 403
            
        # 2. Insere os novos votos
        data_hora_agora = datetime.utcnow()
        novos_votos = [
            Voto(cpf=cpf, turno=turno, candidato=c, data_hora=data_hora_agora)
            for c in votos_recebidos
        ]
        db.session.add_all(novos_votos)
        
        # 3. Atualiza o status do eleitor
        eleitor = Eleitor.query.filter_by(cpf=cpf).first()
        if eleitor:
            try:
                votou_turnos = json.loads(eleitor.votou_turnos)
            except json.JSONDecodeError:
                votou_turnos = {}
            votou_turnos[turno] = True
            eleitor.votou_turnos = json.dumps(votou_turnos, ensure_ascii=False)

        # 4. Atualiza a contagem 'votaram'
        # Conta quantos CPFs únicos votaram *neste turno*
        total_votaram_turno = db.session.query(db.func.count(db.distinct(Voto.cpf))).filter_by(turno=turno).scalar()
        db_set_config('votaram', str(total_votaram_turno))

        # 5. Efetiva a transação
        db.session.commit()
        # --- FIM DA TRANSAÇÃO ---
        
        app.logger.info(f"Voto de {cpf} para {turno} registado com sucesso.")

    except IntegrityError as e:
        db.session.rollback()
        app.logger.warning(f"IntegrityError ao votar (provável voto duplicado): {e}")
        return jsonify({"mensagem": "Erro de integridade, possível voto duplicado."}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro geral ao votar: {e}")
        return jsonify({"mensagem": "Erro interno ao gravar votos."}), 500
    
    session.pop('cpf', None)
    session.pop('turno_atual', None)
    return jsonify({"mensagem": "Votos registrados com sucesso!"}), 200


@app.route('/resultados')
def resultados():
    """ Rota pública (se houver) que mostra os resultados """
    try:
        # Agrupa por turno e candidato e conta os votos
        resultados_db = db.session.query(
            Voto.turno, 
            Voto.candidato, 
            db.func.count(Voto.id)
        ).group_by(Voto.turno, Voto.candidato).all()
        
        resultados = {}
        for turno, candidato, total in resultados_db:
            resultados.setdefault(turno, {})[candidato] = total
            
        return jsonify({'votos_db': resultados})
        
    except Exception as e:
        app.logger.error(f"Erro ao obter /resultados: {e}")
        return jsonify({"erro": "Não foi possível ler resultados do banco."}), 500

# --- Rotas Administrativas ---

def login_obrigatorio(f):
    """ Decorador para proteger rotas administrativas """
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
        
        # Passwords devem estar em variáveis de ambiente!
        ADMIN_USER = os.environ.get('ADMIN_USER', 'jardim2025')
        ADMIN_PASS = os.environ.get('ADMIN_PASS', '02022019')

        if usuario == ADMIN_USER and senha == ADMIN_PASS:
            session['logado'] = True
            return redirect(url_for('admin_page'))
        else:
            # Não use `flash` aqui, passe o erro para o template
            return render_template('login.html', erro="Usuário ou senha incorretos.")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@login_obrigatorio
def admin_page():
    """ Renderiza a página principal do painel admin """
    try:
        config = db_get_config_all()
        turno_atual = config.get('turno_atual', '1º turno')
        candidatos_turno = config.get('candidatos_por_turno', {}).get(turno_atual, [])
        
        # Total de eleitores cadastrados
        total_eleitores = Eleitor.query.count()
        
        # Sincroniza 'presentes' se estiver diferente
        if int(config.get('presentes', 0)) != total_eleitores:
            config['presentes'] = total_eleitores
            db_set_config('presentes', str(total_eleitores))
            db.session.commit()
            
        # Busca votos do turno atual
        votos_db = db.session.query(
            Voto.candidato, 
            db.func.count(Voto.id)
        ).filter_by(turno=turno_atual).group_by(Voto.candidato).all()
        
        resultados = {c: 0 for c in candidatos_turno}
        for candidato, total in votos_db:
            resultados[candidato] = total
            
        presentes = total_eleitores if total_eleitores > 0 else 1 # Evita divisão por zero
        porcentagens = {
            c: round((v / presentes) * 100, 1)
            for c, v in resultados.items()
        }

        return render_template(
            'admin.html',
            config=config, # Passa a config completa para o JS
            resultados=resultados,
            porcentagens=porcentagens,
            turno_atual=turno_atual
        )
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao carregar /admin: {e}")
        return f"Erro ao carregar página admin: {e}", 500


@app.route('/admin/data')
@login_obrigatorio
def admin_data():
    """ Fornece dados JSON para a atualização dinâmica do admin.html """
    try:
        config = db_get_config_all()
        turno_atual = config.get("turno_atual", "1º turno")
        
        # Lista de candidatos do turno atual
        candidatos_do_turno = config.get("candidatos_por_turno", {}).get(turno_atual, [])
        if not candidatos_do_turno:
            candidatos_do_turno = [c['nome'] for c in config.get("candidatos", [])]

        # Contagem de eleitores ("presentes")
        presentes = Eleitor.query.count()
        
        # Contagem de votos por candidato (APENAS do turno atual)
        votos_db = db.session.query(
            Voto.candidato, 
            db.func.count(Voto.id)
        ).filter_by(turno=turno_atual).group_by(Voto.candidato).all()
        
        votos_por_candidato = {cand: 0 for cand in candidatos_do_turno}
        for candidato, total in votos_db:
            votos_por_candidato[candidato] = total

        # Contagem de votantes ÚNICOS (APENAS do turno atual)
        cpfs_votaram_turno = db.session.query(
            db.distinct(Voto.cpf)
        ).filter_by(turno=turno_atual).all()
        votaram = len(cpfs_votaram_turno)
        
        # Sincroniza config ('presentes' e 'votaram')
        if int(config.get('presentes', 0)) != presentes or int(config.get('votaram', 0)) != votaram:
            db_set_config('presentes', str(presentes))
            db_set_config('votaram', str(votaram))
            db.session.commit()
            
        faltam = max(0, presentes - votaram)
        
        # Calcula percentuais
        presentes_calc = presentes if presentes > 0 else 1
        percentuais = {
            c: round((v / presentes_calc) * 100, 1)
            for c, v in votos_por_candidato.items()
        }

        return jsonify({
            "turno_atual": turno_atual,
            "candidatos": candidatos_do_turno, # Lista de nomes
            "votos": votos_por_candidato,      # Dict {nome: total}
            "percent": percentuais,
            "presentes": presentes,
            "votaram": votaram,
            "faltam": faltam,
            "turnos": config.get('turnos', PADRAO_TURNOS), # Lista de nomes de turnos
            "candidatos_por_turno": config.get('candidatos_por_turno', {}), # Dict de listas
            "cpfs_votaram": [cpf[0] for cpf in cpfs_votaram_turno] # Lista de CPFs
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro em /admin/data: {e}")
        return jsonify({"erro": f"Erro ao buscar dados: {e}"}), 500


@app.route('/admin/update_config', methods=['POST'])
@login_obrigatorio
def admin_update_config():
    """ Atualiza as configurações (turnos, candidatos) """
    dados = request.get_json(force=True)
    if not dados:
        return jsonify({"erro": "Pedido inválido."}), 400
        
    try:
        config = db_get_config_all()
        
        # --- Atualiza lista de turnos ---
        if 'turnos_text' in dados:
            turnos_novos = [t.strip() for t in dados['turnos_text'].split(',') if t.strip()]
            if turnos_novos:
                config['turnos'] = turnos_novos
                # Garante que todo turno novo exista em 'candidatos_por_turno'
                for t in turnos_novos:
                    config['candidatos_por_turno'].setdefault(t, ["Voto Nulo"])
                # Se o turno atual foi removido, volta para o primeiro
                if config['turno_atual'] not in turnos_novos:
                    config['turno_atual'] = turnos_novos[0]
        
        # --- Atualiza turno atual ---
        if 'turno_atual' in dados:
            if dados['turno_atual'] in config['turnos']:
                config['turno_atual'] = dados['turno_atual']
                # Ao mudar de turno, recalcula 'votaram'
                votaram_novo_turno = db.session.query(db.func.count(db.distinct(Voto.cpf))).filter_by(turno=config['turno_atual']).scalar()
                config['votaram'] = votaram_novo_turno
                db_set_config('votaram', str(votaram_novo_turno))

        # --- Atualiza candidatos ---
        if 'candidatos_text' in dados:
            nomes_novos = [c.strip() for c in dados['candidatos_text'].split(',') if c.strip()]
            
            # Turno alvo para esta lista de candidatos
            turno_alvo = dados.get('turno_for_candidates') or config['turno_atual']
            config['candidatos_por_turno'][turno_alvo] = nomes_novos
            
            # --- CORREÇÃO: Adiciona/Atualiza candidatos na lista MESTRA ---
            lista_mestra = config.get('candidatos', [])
            nomes_mestres = [c['nome'].lower() for c in lista_mestra]
            
            for nome_novo in nomes_novos:
                if nome_novo.lower() not in nomes_mestres:
                    # É um candidato 100% novo, adiciona na lista mestra
                    app.logger.info(f"Adicionando novo candidato à lista mestra: {nome_novo}")
                    lista_mestra.append({"nome": nome_novo, "foto": None})
                else:
                    # Candidato já existe, verifica se o 'case' (maiúscula/minúscula) mudou
                    for candidato_mestre in lista_mestra:
                        if candidato_mestre['nome'].lower() == nome_novo.lower() and candidato_mestre['nome'] != nome_novo:
                            app.logger.info(f"Corrigindo 'case' do candidato: de '{candidato_mestre['nome']}' para '{nome_novo}'")
                            candidato_mestre['nome'] = nome_novo # Corrige o nome
                            break
                            
            config['candidatos'] = lista_mestra
            db_set_config('candidatos', config['candidatos'])

        # --- Resetar votos ---
        if dados.get('reset_votos'):
            app.logger.warning("RESETANDO TODOS OS VOTOS!")
            # 1. Apaga todos os votos
            db.session.query(Voto).delete()
            
            # 2. Reseta o status de todos os eleitores
            eleitores_todos = Eleitor.query.all()
            for e in eleitores_todos:
                e.votou_turnos = '{}' # Zera o JSON
            
            # 3. Zera a contagem 'votaram' na config
            config['votaram'] = 0
            db_set_config('votaram', '0')

        # --- Salva todas as alterações na config ---
        db_set_config('turnos', config['turnos'])
        db_set_config('turno_atual', config['turno_atual'])
        db_set_config('candidatos_por_turno', config['candidatos_por_turno'])
        
        # Força a contagem de 'presentes' a ser o total de eleitores
        total_eleitores = Eleitor.query.count()
        db_set_config('presentes', str(total_eleitores))

        db.session.commit()
        return jsonify({'mensagem': 'Configurações atualizadas com sucesso.'})

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro em /admin/update_config: {e}")
        return jsonify({'erro': f'Erro ao salvar: {e}'}), 500

# --- ROTAS DE ELEITORES (Agora no DB) ---

@app.route('/admin/eleitores', methods=['GET'])
@login_obrigatorio
def listar_eleitores():
    """ Lista todos os eleitores do banco de dados """
    try:
        eleitores_dict = db_carregar_eleitores_dict()
        return jsonify(eleitores_dict)
    except Exception as e:
        app.logger.error(f"Erro ao listar eleitores: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route('/admin/eleitores', methods=['POST'])
@login_obrigatorio
def adicionar_eleitor():
    """ Adiciona um novo eleitor ao banco de dados """
    dados = request.get_json(force=True)
    cpf = (dados.get('cpf') or '').strip()
    if not cpf or not cpf.isdigit():
        return jsonify({'erro': 'CPF inválido. Use apenas números.'}), 400

    try:
        existente = Eleitor.query.filter_by(cpf=cpf).first()
        if existente:
            return jsonify({'erro': 'CPF já cadastrado.'}), 400
            
        # Pega a lista de turnos da config para criar o JSON 'votou_turnos'
        config = db_get_config_all()
        turnos = config.get('turnos', PADRAO_TURNOS)
        votou_turnos_json = json.dumps({t: False for t in turnos})
        
        novo_eleitor = Eleitor(cpf=cpf, votou_turnos=votou_turnos_json)
        db.session.add(novo_eleitor)
        
        # Atualiza a contagem de 'presentes'
        total_eleitores = Eleitor.query.count() + 1
        db_set_config('presentes', str(total_eleitores))
        
        db.session.commit()
        return jsonify({'mensagem': f'CPF {cpf} cadastrado com sucesso!'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao adicionar eleitor: {e}")
        return jsonify({"erro": str(e)}), 500


@app.route('/admin/eleitores', methods=['PUT'])
@login_obrigatorio
def editar_eleitor():
    """ Edita o CPF de um eleitor """
    dados = request.get_json(force=True)
    cpf_antigo = dados.get('cpf_antigo', '').strip()
    cpf_novo = dados.get('cpf_novo', '').strip()

    if not cpf_novo.isdigit():
        return jsonify({'erro': 'Novo CPF inválido!'}), 400

    try:
        # Verifica se o novo CPF já existe
        novo_existente = Eleitor.query.filter_by(cpf=cpf_novo).first()
        if novo_existente:
            return jsonify({'erro': 'Novo CPF já existente!'}), 400

        eleitor = Eleitor.query.filter_by(cpf=cpf_antigo).first()
        if not eleitor:
            return jsonify({'erro': 'CPF original não encontrado!'}), 404
            
        # Temos que atualizar o CPF na tabela Votos também!
        votos_antigos = Voto.query.filter_by(cpf=cpf_antigo).all()
        for v in votos_antigos:
            v.cpf = cpf_novo
            
        # Atualiza o CPF do eleitor
        eleitor.cpf = cpf_novo
        
        db.session.commit()
        return jsonify({'mensagem': f'Eleitor atualizado para {cpf_novo}.'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao editar eleitor: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route('/admin/eleitores', methods=['DELETE'])
@login_obrigatorio
def excluir_eleitor():
    """ Exclui um eleitor E TODOS OS SEUS VOTOS """
    dados = request.get_json(force=True)
    cpf = dados.get('cpf', '').strip()

    try:
        eleitor = Eleitor.query.filter_by(cpf=cpf).first()
        if not eleitor:
            return jsonify({'erro': 'CPF não encontrado!'}), 404

        # 1. Exclui todos os votos associados a este CPF (CASCADE)
        Voto.query.filter_by(cpf=cpf).delete()
        
        # 2. Exclui o eleitor
        db.session.delete(eleitor)
        
        # 3. Atualiza contagem de 'presentes'
        total_eleitores = Eleitor.query.count() - 1
        db_set_config('presentes', str(total_eleitores))
        
        db.session.commit()
        return jsonify({'mensagem': f'Eleitor {cpf} e todos os seus votos foram removidos.'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao excluir eleitor: {e}")
        return jsonify({"erro": str(e)}), 500


@app.route('/admin/eleitores/all', methods=['DELETE'])
@login_obrigatorio
def excluir_todos_eleitores():
    """ Exclui TODOS os eleitores E TODOS os votos """
    try:
        # Ordem importa: primeiro os votos, depois os eleitores
        num_votos = db.session.query(Voto).delete()
        num_eleitores = db.session.query(Eleitor).delete()
        
        # Zera contagens
        db_set_config('presentes', '0')
        db_set_config('votaram', '0')
        
        db.session.commit()
        return jsonify({'mensagem': f'Todos os {num_eleitores} eleitores e {num_votos} votos foram apagados com sucesso.'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao excluir todos os eleitores: {e}")
        return jsonify({"erro": str(e)}), 500

# --- Inicialização ---
# Cria as tabelas e popula a config se for a primeira vez
db_inicializar()
    
if __name__ == '__main__':
    # O Render define a porta pela variável PORT
    port = int(os.environ.get('PORT', 5000))
    
    # O Gunicorn (usado pelo Render) vai gerir o 'host' e 'workers'
    # Esta linha é usada apenas para testes locais (ex: `python app.py`)
    app.run(host='0.0.0.0', port=port, debug=False)

