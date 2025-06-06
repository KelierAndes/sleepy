#!/usr/bin/python3
# coding: utf-8
import os
import requests
import re
import time
import json5
# import importlib  # for plugin
import pytz
import flask
import asyncio
from datetime import datetime
from markupsafe import escape
from functools import wraps  # 用于修饰器

import utils as u
import env
from data import data as data_init
from setting import status_list

try:
    # init flask app
    app = flask.Flask(__name__)

    # disable flask access log (if not debug)
    if not env.main.debug:
        from logging import getLogger
        flask_default_logger = getLogger('werkzeug')
        flask_default_logger.disabled = True

    # init data
    d = data_init()
    d.load()
    d.start_timer_check(data_check_interval=env.main.checkdata_interval)  # 启动定时保存

    # init metrics if enabled
    if env.util.metrics:
        u.info('[metrics] metrics enabled, open /metrics to see your count.')
        d.metrics_init()
except Exception as e:
    u.error(f"Error initing: {e}")
    exit(1)
except KeyboardInterrupt:
    u.debug('Interrupt init')
    exit(0)
except u.SleepyException as e:
    u.error(f'==========\n{e}')
    exit(1)
except:
    u.error('Unexpected Error!')
    raise


# --- Functions


@app.before_request
def showip():
    '''
    在日志中显示 ip, 并记录 metrics 信息
    ~~如 Header 中 User-Agent 为 SleepyPlugin/(每次启动使用随机 uuid) 则不进行任何记录~~

    :param req: `flask.request` 对象, 用于取 ip
    :param msg: 信息 (一般是路径, 同时作为 metrics 的项名)
    '''
    # --- get path
    path = flask.request.path
    # --- log
    ip1 = flask.request.remote_addr
    ip2 = flask.request.headers.get('X-Forwarded-For')
    if ip2:
        u.info(f'- Request: {ip1} / {ip2} : {path}')
    else:
        u.info(f'- Request: {ip1} : {path}')
    # --- count
    if env.util.metrics:
        d.record_metrics(path)


def require_secret(view_func):
    '''
    require_secret 修饰器, 用于指定函数需要 secret 鉴权
    '''
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        # 1. body
        body: dict = flask.request.get_json(silent=True) or {}
        if body and body.get('secret') == env.main.secret:
            u.debug('[Auth] Verify secret Success from Body')
            return view_func(*args, **kwargs)

        # 2. param
        elif flask.request.args.get('secret') == env.main.secret:
            u.debug('[Auth] Verify secret Success from Param')
            return view_func(*args, **kwargs)

        # 3. header (Sleepy-Secret)
        # -> Sleepy-Secret: my-secret
        elif flask.request.headers.get('Sleepy-Secret') == env.main.secret:
            u.debug('[Auth] Verify secret Success from Header (Sleepy-Secret)')
            return view_func(*args, **kwargs)

        # 4. header (Authorization)
        # -> Authorization: Bearer my-secret
        elif flask.request.headers.get('Authorization')[7:] == env.main.secret:
            u.debug('[Auth] Verify secret Success from Header (Authorization)')
            return view_func(*args, **kwargs)

        # -1. no any secret
        u.debug('[Auth] Verify secret Failed')
        return u.reterr(
            code='not authorized',
            message='wrong secret'
        )
    return wrapped_view

# --- Templates


@app.route('/')
def index():
    '''
    根目录返回 html
    - Method: **GET**
    '''
    try:
        stat = status_list[d.data['status']]
    except:
        u.debug(f"Index {d.data['status']} out of range!")
        stat = {
            'name': 'Unknown',
            'desc': '未知的标识符，可能是配置问题。',
            'color': 'error'
        }
    more_text: str = env.page.more_text
    if env.util.metrics:
        more_text = more_text.format(
            visit_today=d.data['metrics']['today'].get('/', 0),
            visit_month=d.data['metrics']['month'].get('/', 0),
            visit_year=d.data['metrics']['year'].get('/', 0),
            visit_total=d.data['metrics']['total'].get('/', 0)
        )
    return flask.render_template(
        'index.html',
        page_title=env.page.title,
        page_desc=env.page.desc,
        page_favicon=env.page.favicon,
        user=env.page.user,
        learn_more=env.page.learn_more,
        repo=env.page.repo,
        more_text=more_text,
        hitokoto=env.page.hitokoto,
        canvas=env.page.canvas,
        moonlight=env.page.moonlight,
        lantern=env.page.lantern,
        mplayer=env.page.mplayer,
        bg=env.page.background,

        steam_legacy_enabled=env.util.steam_legacy_enabled,
        steam_enabled=env.util.steam_enabled,
        steamkey=env.util.steam_key,
        steamids=env.util.steam_ids,

        status_name=stat['name'],
        status_color=stat['color'],
        status_desc=stat['desc'],

        last_updated=d.data['last_updated'],
        debug=env.main.debug
    )


@app.route('/'+'git'+'hub')
def git_hub():
    '''
    这里谁来了都改不了!
    '''
    return flask.redirect('ht'+'tps:'+'//git'+'hub.com/'+'wyf'+'9/sle'+'epy', 301)


@app.route('/none')
def none():
    '''
    返回 204 No Content, 可用于 Uptime Kuma 等工具监控服务器状态使用
    '''
    return '', 204


# --- Read-only


@app.route('/query')
def query(ret_as_dict: bool = False):
    '''
    获取当前状态
    - 无需鉴权
    - Method: **GET**

    :param ret_as_dict: 使函数直接返回 dict 而非 u.format_dict() 格式化后的 response
    '''
    st: int = d.data['status']
    try:
        stinfo = status_list[st]
    except:
        stinfo = {
            'id': -1,
            'name': '[未知]',
            'desc': f'未知的标识符 {st}，可能是配置问题。',
            'color': 'error'
        }
    devicelst = d.data['device_status']
    if d.data['private_mode']:
        devicelst = {}
    timenow = datetime.now(pytz.timezone(env.main.timezone))
    ret = {
        'time': timenow.strftime('%Y-%m-%d %H:%M:%S'),
        'timezone': env.main.timezone,
        'success': True,
        'status': st,
        'info': stinfo,
        'device': devicelst,
        'device_status_slice': env.status.device_slice,
        'last_updated': d.data['last_updated'],
        'refresh': env.status.refresh_interval
    }
    if ret_as_dict:
        return ret
    else:
        return u.format_dict(ret)


@app.route('/status_list')
def get_status_list():
    '''
    获取 `status_list`
    - 无需鉴权
    - Method: **GET**
    '''
    stlst = status_list
    return u.format_dict(stlst)


# --- Status API


@app.route('/set')
@require_secret
def set_normal():
    '''
    设置状态
    - http[s]://<your-domain>[:your-port]/set?status=<a-number>
    - Method: **GET**
    '''
    status = escape(flask.request.args.get('status'))
    try:
        status = int(status)
    except:
        return u.reterr(
            code='bad request',
            message="argument 'status' must be int"
        )
    d.dset('status', status)
    return u.format_dict({
        'success': True,
        'code': 'OK',
        'set_to': status
    })


# --- Device API

@app.route('/device/set', methods=['GET', 'POST'])
@require_secret
def device_set():
    '''
    设置单个设备的信息/打开应用
    - Method: **GET / POST**
    '''
    if flask.request.method == 'GET':
        try:
            device_id = escape(flask.request.args.get('id'))
            device_show_name = escape(flask.request.args.get('show_name'))
            device_using = u.tobool(escape(flask.request.args.get('using')), throw=True)
            app_name = escape(flask.request.args.get('app_name'))
        except:
            return u.reterr(
                code='bad request',
                message='missing param or wrong param type'
            )
    elif flask.request.method == 'POST':
        req = flask.request.get_json()
        try:
            device_id = req['id']
            device_show_name = req['show_name']
            device_using = u.tobool(req['using'], throw=True)
            app_name = req['app_name']
        except:
            return u.reterr(
                code='bad request',
                message='missing param or wrong param type'
            )
    devices: dict = d.dget('device_status')
    if (not device_using) and env.status.not_using:
        # 如未在使用且锁定了提示，则替换
        app_name = env.status.not_using
    devices[device_id] = {
        'show_name': device_show_name,
        'using': device_using,
        'app_name': app_name
    }
    d.data['last_updated'] = datetime.now(pytz.timezone(env.main.timezone)).strftime('%Y-%m-%d %H:%M:%S')
    d.check_device_status()
    return u.format_dict({
        'success': True,
        'code': 'OK'
    })


@app.route('/device/remove')
@require_secret
def remove_device():
    '''
    移除单个设备的状态
    - Method: **GET**
    '''
    device_id = escape(flask.request.args.get('id'))
    try:
        del d.data['device_status'][device_id]
        d.data['last_updated'] = datetime.now(pytz.timezone(env.main.timezone)).strftime('%Y-%m-%d %H:%M:%S')
        d.check_device_status()
    except KeyError:
        return u.reterr(
            code='not found',
            message='cannot find item'
        )
    return u.format_dict({
        'success': True,
        'code': 'OK'
    })


@app.route('/device/clear')
@require_secret
def clear_device():
    '''
    清除所有设备状态
    - Method: **GET**
    '''
    d.data['device_status'] = {}
    d.data['last_updated'] = datetime.now(pytz.timezone(env.main.timezone)).strftime('%Y-%m-%d %H:%M:%S')
    d.check_device_status()
    return u.format_dict({
        'success': True,
        'code': 'OK'
    })


@app.route('/device/private_mode')
@require_secret
def private_mode():
    '''
    隐私模式, 即不在 /query 中显示设备状态 (仍可正常更新)
    - Method: **GET**
    '''
    private = u.tobool(escape(flask.request.args.get('private')))
    if private == None:
        return u.reterr(
            code='invaild request',
            message='"private" arg only supports boolean type'
        )
    d.data['private_mode'] = private
    d.data['last_updated'] = datetime.now(pytz.timezone(env.main.timezone)).strftime('%Y-%m-%d %H:%M:%S')
    return u.format_dict({
        'success': True,
        'code': 'OK'
    })


@app.route('/save_data')
@require_secret
def save_data():
    '''
    保存内存中的状态信息到 `data.json`
    - Method: **GET**
    '''
    try:
        d.save()
    except Exception as e:
        return u.reterr(
            code='exception',
            message=f'{e}'
        )
    return u.format_dict({
        'success': True,
        'code': 'OK',
        'data': d.data
    })


@app.route('/events')
def events():
    '''
    SSE 事件流，用于推送状态更新
    - Method: **GET**
    '''
    def event_stream():
        last_update = None
        last_heartbeat = time.time()
        while True:
            current_time = time.time()
            # 检查数据是否已更新
            current_update = d.data['last_updated']

            # 如果数据有更新，发送更新事件并重置心跳计时器
            if last_update != current_update:
                last_update = current_update
                # 重置心跳计时器
                last_heartbeat = current_time

                # 获取 /query 返回数据
                ret = query(ret_as_dict=True)
                yield f"event: update\ndata: {json5.dumps(ret, quote_keys=True)}\n\n"
            # 只有在没有数据更新的情况下才检查是否需要发送心跳
            elif current_time - last_heartbeat >= 30:
                timenow = datetime.now(pytz.timezone(env.main.timezone))
                yield f"event: heartbeat\ndata: {timenow.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                last_heartbeat = current_time

            time.sleep(1)  # 每秒检查一次更新

    response = flask.Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"  # 禁用缓存
    response.headers["X-Accel-Buffering"] = "no"  # 禁用 Nginx 缓冲
    return response

def massage_send(sendkey, title, desp='', options=None):
    if sendkey == '':
        sendkey = env.main.sendkey
    if options is None:
        options = {
            "tags": "网页推送"
        }
    # 判断 sendkey 是否以 'sctp' 开头，并提取数字构造 URL
    if sendkey.startswith('sctp'):
        match = re.match(r'sctp(\d+)t', sendkey)
        if match:
            num = match.group(1)
            url = f'https://{num}.push.ft07.com/send/{sendkey}.send'
        else:
            raise ValueError('Invalid sendkey format for sctp')
    else:
        url = f'https://sctapi.ftqq.com/{sendkey}.send'
    params = {
        'title': title,
        'desp': desp,
        **options
    }
    headers = {
        'Content-Type': 'application/json;charset=utf-8'
    }
    response = requests.post(url, json=params, headers=headers)
    u.info(response.text)

async def DgStart():
    try:
        if d.data['DGLab']['fire']:
            postData = {"strength": d.data['DGLab']['strength'],"time":str(1000*int(d.data['DGLab']['duration'])),"override":'true'}
            u.info(str(postData))
            url = d.data['DGLab']['url']+"/api/v2/game/all/action/fire"
            response = requests.post(url, data=postData, proxies={})
        else:
            postData = {"strength.set": d.data['DGLab']['strength']}
            url = d.data['DGLab']['url']+"/api/v2/game/all/strength"
            response = requests.post(url, data=postData, proxies={})
            await asyncio.sleep(int(d.data['DGLab']['duration']))
            response = requests.post(url, data={"strength.set": "0"}, proxies={})
        
        u.info(response.text)
        return "操作成功"  # 成功时返回成功信息
    except Exception as e:
        u.error(f"发生错误: {e}")
        return f"发生错误: {e}"  # 捕获异常并返回错误信息

async def DgRun():
    result = await DgStart() # 调用 DgStart 并捕获返回值
    massage = f"有人戳了你一下\n郊狼运行状态: {result}"
    result1 = "信息发送完成"
    if result == "操作成功":
        result2 = f"郊狼运行完成，强度{d.data['DGLab']['strength']}，持续{d.data['DGLab']['duration']}秒！"
        result3 = result2
    else:
        result2 = f"郊狼运行失败, 错误信息: {result}"
        result3 = ''
    massage_send('', '网页状态推送', massage) 
    u.info(f"{result1}\n{result2}")
    return f"{result1}\n{result3}"  # 将 DgStart 的返回值加入响应
@app.route("/button1", methods=["POST"])
def button1_click():
    buttonreturn = asyncio.run(DgRun())
    return buttonreturn

# --- Special

if env.util.metrics:
    @app.route('/metrics')
    def metrics():
        '''
        获取统计信息
        - Method: **GET**
        '''
        resp = d.get_metrics_resp()
        return resp

if env.util.steam_enabled:
    @app.route('/steam-iframe')
    def steam():
        return flask.render_template(
            'steam-iframe.html',
            steamids=env.util.steam_ids
        )

# --- End

if __name__ == '__main__':
    u.info(f'=============== hi {env.page.user}! ===============')
    # --- plugins - undone
    # u.info(f'Loading plugins...')
    # all_plugins = u.list_dir(u.get_path('plugin'), include_subfolder=False, ext='.py')
    # enabled_plugins = []
    # for i in all_plugins:
    #     pass
    # --- launch
    u.info(f'Starting server: {env.main.host}:{env.main.port}{" (debug enabled)" if env.main.debug else ""}')
    try:
        app.run(  # 启↗动↘
            host=env.main.host,
            port=env.main.port,
            debug=env.main.debug
        )
    except Exception as e:
        u.error(f"Error running server: {e}")
    print()
    u.info('Server exited, saving data...')
    d.save()
    u.info('Bye.')