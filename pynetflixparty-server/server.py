'''
Created on Mar 31, 2016

@author: Philip

This code is designed to go into wsgi.py on OpenShift.  It shouldn't take too many changes to make it work
on your own server or another cloud platform.
'''
#!/usr/bin/python


import os
from inspect import isclass
from datetime import datetime

virtenv = os.environ['OPENSHIFT_PYTHON_DIR'] + '/virtenv/'
virtualenv = os.path.join(virtenv, 'bin/activate_this.py')
try:
	execfile(virtualenv, dict(__file__=virtualenv))

except IOError:
	pass
#
# IMPORTANT: Put any additional includes below this line.  If placed above this
# line, it's possible required libraries won't be in your searchable path
#

import socketio
import random
import logging
import json
import re
from datetime import datetime
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logFile="log.txt"



def writeToLog(txt):
	file = open(logFile, 'a')
	file.write(datetime.now().ctime() + ' - ' + txt + '\n')
	file.flush()
	file.close()
	
writeToLog("***Log file opened***")

class session:
	id = 0
	lastKnownTime = 0
	lastKnownTimeUpdatedAt = 0
	messages = []
	ownerId = ""
	state = 'paused'
	userIds = []
	videoId = 0

	def __init__(self, uId, lastKnownTime, lastKnownTimeUpdatedAt, messages, ownerId, state, userIds, videoId):
		self.id = uId
		self.lastKnownTime = lastKnownTime
		self.lastKnownTimeUpdatedAt = lastKnownTimeUpdatedAt
		self.messages = messages
		self.ownerId = ownerId
		self.state = state
		self.userIds = userIds
		self.videoId = videoId


class user:

	def __init__(self, uId, sessionId):
		self.id = uId
		self.sessionId = sessionId
		self.typing = False


sessions = dict()
users = dict()

io = socketio.Server()

# generate a random ID with 64 bits of entropy


def makeId():
	result = ''
	hexChars = '0123456789abcdef'
	for i in xrange(0, len(hexChars)):
		result += hexChars[random.randint(0, len(hexChars) - 1)]

	return result


def isNumber(number):
	return isinstance(number, (int, long, float, complex)) and not isinstance(number, bool)


def toTimestampSeconds(dt):
	return (dt - datetime(1970, 1, 1)).total_seconds()


#validation functions
def validateId(uId):
	return isinstance(id, basestring) and len(uId) == 16


def validateLastKnownTime(lastKnownTime):
	return isNumber(lastKnownTime) and lastKnownTime % 1 == 0 and lastKnownTime >= 0


def validateTimestamp(timestamp):
	validateLastKnownTime(timestamp)


def validateBoolean(b):
	return (str(b).lower() == 'true' or str(b).lower() == 'false')


def validateMessages(messages):
	if (messages == None or isNumber(len(messages))):
		return False

	for i in messages:
		if hasattr(messages, i):
			i = int(i)
			if math.isnan(i):
				return False

			if (not isNumber(i) or i % 1 != 0 or i < 0 or i >= len(messages)):
				return False

			if (not isclass(messages[i]) or messages[i] == None):
				return False

			if (not validateMessageBody(messages[i].body)):
				return False

			if (messages[i].isSystemMessage == None):
				messages[i].isSystemMessage = False

			if (not validateBoolean(messages[i].isSystemMessage)):
				return False

			if (not validateTimestamp(messages[i].timestamp)):
				return False
			
			if (not validateId(messages[i].userId)):
				return False



	return True

def validateState(state):
	return isinstance(state, basestring) and (state == 'playing' or state == 'paused')

def validateVideoId(videoId):
	return isNumber(videoId) and videoId % 1 == 0 and videoId >= 0

def validateMessageBody(body):
	return isinstance(body, basestring) and not re.sub(r'/^\s+|\s+$/g', '', body) == ''

def padIntegerWithZeros(x, minWidth):
	numStr = str(x)
	while (len(numStr) < minWidth):
		numStr = '0' + numStr

	return numStr

@io.on('connect')
def onConnection(sid, a2):
	userId = sid
	users[sid] = user(userId, None)

	io.emit("userId", data=str(userId), room=sid)
	writeToLog('User ' + userId + ' connected.')
	
	# precondition: sessionId is the id of a session
	# precondition: notToThisUserId is the id of a user, or null
def broadcastPresence(sessionId, notToThisUserId):
	anyoneTyping = False
	
	for i in xrange(0, len(sessions[sessionId].userIds)):
		if (users[sessions[sessionId].userIds[i]].typing):
			anyoneTyping = True
			break

	for uId in sessions[sessionId].userIds:
		if not uId == notToThisUserId:
			writeToLog('Sending presence to user ' + uId + '.')
			io.emit('setPresence', {'anyoneTyping': anyoneTyping}, uId)
			
# precondition: user userId is in a session
# precondition: body is a string
# precondition: isSystemMessage is a boolean
def sendMessage(body, isSystemMessage, userId):
	message = dict(body = body, 
				isSystemMessage = isSystemMessage, 
				timestamp = toTimestampSeconds(datetime.now()), 
				userId = userId
				)
	sessions[users[userId].sessionId].messages.append(message)
	
	for uId in sessions[users[userId].sessionId].userIds:
		writeToLog('Sending message to user' + uId + '.')
		io.emit('sendMessage', message, uId)
		
# precondition: user userId is in a session
def leaveSession(userId):
	sendMessage('left', True)
	
	sessionId = users[userId].sessionId
	
	sessions[sessionId].userIds.remove(userId)
	
	users[userId].sessionId = None
	
	
	if len(sessions[sessionId].userIds) == 0:
		del sessions[sessionId]
		writeToLog('Session ' + sessionId + ' was deleted because there were no more users in it.')
	else:
		broadcastPresence(sessionId, None)

@io.on('reboot')
def onReboot(sid, data):
	writeToLog("reboot event received")
# 	if (not userId in users):
# 		fn(dict( errorMessage = 'Disconnected.'))
# 		return
# 	
# 	if (not validateId(data.sessionId)):
# 		fn(dict( errorMessage = 'Invalid session ID.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot invalid session ' + json.dumps(data.sessionId) + '.')
# 		return
# 	
# 	if (not validateLastKnownTime(data.lastKnownTime)):
# 		fn(dict( errorMessage = 'Invalid lastKnownTime.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTime ' + json.dumps(data.lastKnownTime) + '.')
# 		return
# 
# 	if (not validateTimestamp(data.lastKnownTimeUpdatedAt)):
# 		fn(dict( errorMessage = 'Invalid lastKnownTimeUpdatedAt.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTimeUpdatedAt ' + json.dumps(data.lastKnownTimeUpdatedAt) + '.')
# 		return
# 	
# 	if (not validateMessages(data.messages)):
# 		fn(dict( errorMessage = 'Invalid messages.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot session with invalid messages ' + json.dumps(data.messages) + '.')
# 		return
# 	
# 	if (not data.ownerId == None and not validateId(data.ownerId)):
# 		fn(dict( errorMessage = 'Invalid ownerId.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot invalid ownerId ' + json.dumps(data.ownerId) + '.')
# 		return
# 	
# 	if (not validateState(data.state)):
# 		fn(dict( errorMessage = 'Invalid state.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid state ' + json.dumps(data.state) + '.')
# 		return
# 	
# 	if (not validateId(data.userId)):
# 		fn(dict( errorMessage = 'Invalid userId.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid userId ' + json.dumps(data.userId) + '.')
# 		return
# 	
# 	if (not validateVideoId(data.videoId)):
# 		fn(dict( errorMessage = 'Invalid video ID.' ))
# 		writeToLog('User ' + userId + ' attempted to reboot session with invalid video ' + json.dumps(data.videoId) + '.')
# 		return
# 	
# 	if (not users[userId].sessionId == None):
# 		sessions[users[userId].sessionId].userIds.remove(userId)
# 		if (sessions[users[userId].sessionId].userIds.length == 0):
# 			del sessions[users[userId].sessionId]
# 	
# 	if (not userId == data.userId):
# 		users[data.userId] = users[userId]
# 		del users[userId]
# 		userId = data.userId
# 		
# 	if (sessions.count(data.sessionId) > 0):
# 		sessions[data.sessionId].userIds.push(userId)
# 		users[userId].sessionId = data.sessionId
# 		writeToLog('User ' + userId + ' reconnected and rejoined session ' + users[userId].sessionId + '.')
# 	else:
# 		tempMessages = []
# 		for msg in data.messages:	
# 			tempMessages.append(dict(
# 								userId= msg.userId,
# 								body= msg.body,
# 								isSystemMessage= msg.isSystemMessage,
# 								timestamp= datetime.fromtimestamp(msg.timestamp)
# 								)
# 							)		
# 		session = dict(
# 				id = data.sessionId,
# 				lastKnownTime = data.lastKnownTime,
# 				lastKnownTimeUpdatedAt = datetime.fromtimestamp(data.lastKnownTimeUpdatedAt),
# 
# 				messages = tempMessages,
# 				ownerId = data.ownerId,
# 				state = data.state,
# 				videoId = data.videoId,
# 				userIds = [userId]
# 				)
# 		sessions[session.id] = session
# 		users[userId].sessionId = data.sessionId
# 		writeToLog('User ' + userId + ' rebooted session ' + users[userId].sessionId + ' with video ' + json.dumps(data.videoId) + ', time ' + json.dumps(data.lastKnownTime) + ', and state ' + data.state + ' for epoch ' + json.dumps(data.lastKnownTimeUpdatedAt) + '.')
# 		
# 	fn(dict(
# 		lastKnownTime= sessions[data.sessionId].lastKnownTime,
# 		lastKnownTimeUpdatedAt= toTimestampSeconds(sessions[data.sessionId].lastKnownTimeUpdatedAt,
# 		state= sessions[data.sessionId].state
# 		)))
# 	
@io.on('createSession')
def onCreateSession(sid, data):
	userId = sid
	
	if (not userId in users):
		logger.log('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (not validateBoolean(data['controlLock'])):
		writeToLog('User ' + userId + ' attempted to create session with invalid controlLock ' + json.dumps(data['controlLock']) + '.')
		return dict( errorMessage = 'Invalid controlLock.' )
	
	if (not validateVideoId(data['videoId'])):
		writeToLog('User ' + userId + ' attempted to create session with invalid video ' + json.dumps(data['videoId']) + '.')
		return dict( errorMessage = 'Invalid video ID.' )
	
	users[userId].sessionId = makeId()
	now = datetime.now()
	
	theSession = session(users[userId].sessionId, 
						0, 
						now, 
						[], 
						userId if data['controlLock'] else None, 
						'paused', 
						[userId], 
						data['videoId']
						)
	
	sessions[theSession.id] = theSession
	
	tempMessages = []
	for msg in sessions[users[userId].sessionId].messages:
		tempMessages.append(dict(body = msg['body'],
								isSystemMessage = msg['isSystemMessage'],
								timestamp = toTimestampSeconds(msg['timestamp']),
								userId = msg['userId']
								
								)
							)
	
	if (str(data['controlLock']).lower() == 'true'):
		sendMessage('created the session with exclusive control', True, userId)
	else:
		sendMessage('created the session', True, userId)
	
	writeToLog('User ' + userId + ' created session ' + users[userId].sessionId + ' with video ' + json.dumps(data['videoId']) + ' and controlLock ' + json.dumps(data['controlLock']) + '.')
	
	return dict(
		lastKnownTime = sessions[users[userId].sessionId].lastKnownTime,
		lastKnownTimeUpdatedAt = toTimestampSeconds(sessions[users[userId].sessionId].lastKnownTimeUpdatedAt),
		messages = tempMessages,
		sessionId = users[userId].sessionId,
		state = sessions[users[userId].sessionId].state
		)
	
# 
# 	@socket.on('joinSession')
# 	def onJoinSession(sessionId, fn):
# 		if (not userId in users):
# 			fn(dict( errorMessage = 'Disconnected.' ))
# 			writeToLog('The socket received a message after it was disconnected.')
# 			return
# 		
# 		if (not validateId(sessionId) or not hasattr(sessions,sessionId)):
# 			fn(dict( errorMessage = 'Invalid session ID.' ))
# 			writeToLog('User ' + userId + ' attempted to join nonexistent session ' + json.dumps(sessionId) + '.')
# 			return
# 		
# 		if (not users[userId].sessionId == None):
# 			fn(dict( errorMessage = 'Already in a session.' ))
# 			writeToLog('User ' + userId + ' attempted to join session ' + sessionId + ', but the user is already in session ' + users[userId].sessionId + '.')
# 			return
# 		
# 		users[userId].sessionId = sessionId
# 		sessions[sessionId].userIds.push(userId)
# 		sendMessage('joined', True)
# 		
# 		tempMessages = []
# 		for msg in sessions[sessionId].messages:
# 			tempMessages.append(dict(
# 									body = msg.body,
# 									isSystemMessage = msg.isSystemMessage,
# 									timestamp = toTimestampSeconds(msg.timestamp),
# 									userId = msg.userId)
# 							)
# 		
# 		fn(dict(
# 		videoId = sessions[sessionId].videoId,
# 		lastKnownTime = sessions[sessionId].lastKnownTime,
# 		lastKnownTimeUpdatedAt = sessions[sessionId].lastKnownTimeUpdatedAt.getTime(),
# 		messages = tempMessages,
# 		ownerId = sessions[sessionId].ownerId,
# 		state = sessions[sessionId].state
# 		))
# 		
# 		writeToLog('User ' + userId + ' joined session ' + sessionId + '.')
# 		
# 	@socket.on('leaveSession')
# 	def onLeaveSession(_, fn):
# 		if (not userId in users):
# 			fn(dict( errorMessage = 'Disconnected.' ))
# 			writeToLog('The socket received a message after it was disconnected.')
# 			return
# 		
# 		if (users[userId].sessionId == None):
# 			fn(dict( errorMessage = 'Not in a session.' ))
# 			writeToLog('User ' + userId + ' attempted to leave a session, but the user was not in one.')
# 			return
# 		
# 		sessionId = users[userId].sessionId
# 		leaveSession()
# 	
# 		fn(None)
# 		writeToLog('User ' + userId + ' left session ' + sessionId + '.')
# 		
@io.on('updateSession')
def onUpdateSession(sid, data):
	userId = sid
	if (not userId in  users):
		writeToLog('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (users[userId].sessionId == None):
		writeToLog('User ' + userId + ' attempted to update a session, but the user was not in one.')
		return dict( errorMessage = 'Not in a session.' )
	
	if (not validateLastKnownTime(data['lastKnownTime'])):
		writeToLog('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTime ' + json.dumps(data['lastKnownTime']) + '.')
		return dict( errorMessage = 'Invalid lastKnownTime.' )
	
	if (not validateTimestamp(data['lastKnownTimeUpdatedAt'])):
		writeToLog('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTimeUpdatedAt ' + json.dumps(data['lastKnownTimeUpdatedAt']) + '.')
		return dict( errorMessage = 'Invalid lastKnownTimeUpdatedAt.' )
	
	if (not validateState(data['state'])):
		writeToLog('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid state ' + json.dumps(data['state']) + '.')
		return dict( errorMessage = 'Invalid state.' )
	
	if (not sessions[users[userId].sessionId].ownerId == None and not sessions[users[userId].sessionId].ownerId == userId):
		writeToLog('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' but the session is locked by ' + sessions[users[userId].sessionId].ownerId + '.')
		return dict( errorMessage = 'Session locked.' )
	
	now = toTimestampSeconds(datetime.now())
	oldPredictedTime = sessions[users[userId].sessionId].lastKnownTime + \
	(0 if sessions[users[userId].sessionId].state == 'paused' else (
																now - toTimestampSeconds(sessions[users[userId].sessionId].lastKnownTimeUpdatedAt)
																))
	
	newPredictedTime = data.lastKnownTime + \
	(0 if data.state == 'paused' else (now - data.lastKnownTimeUpdatedAt))
	
	stateUpdated = not sessions[users[userId].sessionId].state == data.state
	timeUpdated = abs(newPredictedTime - oldPredictedTime) > 2500
	
	hours = math.floor(newPredictedTime / (1000 * 60 * 60))
	newPredictedTime -= hours * 1000 * 60 * 60
	minutes = math.floor(newPredictedTime / (1000 * 60))
	newPredictedTime -= minutes * 1000 * 60
	seconds = math.floor(newPredictedTime / 1000)
	newPredictedTime -= seconds * 1000
	
	timeStr = ''
	if (hours > 0):
		timeStr = str(hours) + ':' + str(minutes) + ':' + padIntegerWithZeros(seconds, 2)
	else:
		timeStr = str(minutes) + ':' + padIntegerWithZeros(seconds, 2)
		
	sessions[users[userId].sessionId].lastKnownTime = data['lastKnownTime']
	sessions[users[userId].sessionId].lastKnownTimeUpdatedAt = datetime.fromtimestamp(data['lastKnownTimeUpdatedAt'])
	sessions[users[userId].sessionId].state = data['state']
	
	if (stateUpdated and timeUpdated):
		if (data['state'] == 'playing'):
			sendMessage('started playing the video at ' + timeStr, True)
		else:
			sendMessage('paused the video at ' + timeStr, True)
	elif (stateUpdated):
		if (data['state'] == 'playing'):
			sendMessage('started playing the video', True)
		else:
			sendMessage('paused the video', True)
	elif (timeUpdated):
		sendMessage('jumped to ' + timeStr, True)
		
	writeToLog('User ' + userId + ' updated session ' + users[userId].sessionId + ' with time ' + json.dumps(data['lastKnownTime']) + ' and state ' + data['state'] + ' for epoch ' + json.dumps(data['lastKnownTimeUpdatedAt']) + '.')
	
	for uId in sessions[users[userId].sessionId].userIds:
		writeToLog('Sending update to user ' + uId + '.')
		if (not uId == userId):
			users[userId].socket.emit('update', dict(
												lastKnownTime = sessions[users[userId].sessionId].lastKnownTime,
												lastKnownTimeUpdatedAt = sessions[users[userId].sessionId].lastKnownTimeUpdatedAt,
												state = sessions[users[userId].sessionId].state)
									)
# 
# 	@socket.on('typing')
# 	def onTyping(data, fn):
# 		if (not userId in users):
# 			fn(dict( errorMessage = 'Disconnected.' ))
# 			writeToLog('The socket received a message after it was disconnected.')
# 			return
# 		
# 		if (users[userId].sessionId == None):
# 			fn(dict( errorMessage = 'Not in a session.' ))
# 			writeToLog('User ' + userId + ' attempted to set presence, but the user was not in a session.')
# 			return
# 		
# 		if (not validateBoolean(data.typing)):
# 			fn(dict( errorMessage = 'Invalid typing.' ))
# 			writeToLog('User ' + userId + ' attempted to set invalid presence ' + json.dumps(data.typing) + '.')
# 			return
# 		
# 		users[userId].typing = data.typing
# 		
# 		fn()
# 		
# 		if (users[userId].typing):
# 			writeToLog('User ' + userId + ' is typing...')
# 		else:
# 			writeToLog('User ' + userId + ' is done typing.')
# 			
# 		broadcastPresence(users[userId].sessionId, userId)
# 		
# 	@socket.on('sendMessage')
# 	def onSendMessage(data, fn):
# 		if (not userId in users):
# 			fn(dict( errorMessage = 'Disconnected.' ))
# 			writeToLog('The socket received a message after it was disconnected.')
# 			return
# 		
# 		if (users[userId].sessionId == None):
# 			fn(dict( errorMessage = 'Not in a session.' ))
# 			writeToLog('User ' + userId + ' attempted to send a message, but the user was not in a session.')
# 			return
# 		
# 		if (not validateMessageBody(data.body)):
# 			fn(dict( errorMessage = 'Invalid message body.' ))
# 			writeToLog('User ' + userId + ' attempted to send an invalid message ' + json.dumps(data.body) + '.')
# 			return
# 		
# 		sendMessage(data.body, False)
# 		fn()
# 		writeToLog('User ' + userId + ' sent message ' + data.body + '.')
# 		
@io.on('getServerTime')
def onGetServerTime(sid, data):
	writeToLog(str(data))
	if (not sid in users):
		writeToLog('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (data != None and isinstance(data['version'], basestring)):
		writeToLog('User ' + sid + ' pinged with version ' + data['version'] + '.')
	else:
		writeToLog('User ' + sid + ' pinged.')
		
	return toTimestampSeconds(datetime.now())
		
@io.on('disconnect')
def onDisconnect(sid):
	if (not sid in users):
		writeToLog('The socket received a message after it was disconnected.')
		return
	if (users[sid].sessionId != None):
		leaveSession()
		
	del users[sid]
	writeToLog('User ' + sid + ' disconnected.')
	
@io.on('error')
def onError(e):
	writeToLog(e)
		
#   server = http.listen(process.env.PORT || 3000, function() {
#   writeToLog('Listening on port %d.', server.address().port);
# });
	
def app(environ, start_response):

	ctype = 'text/plain'
	pathInfo = environ['PATH_INFO']
	if pathInfo == '/health':
		response_body = "1"
	elif pathInfo == '/env':
		response_body = ['%s: %s' % (key, value)
					for key, value in sorted(environ.items())]
		response_body = '\n'.join(response_body)
	elif pathInfo == '/number-of-sessions':
		response_body = str(len(sessions))
	elif pathInfo == '/number-of-users':
		response_body = str(len(users))
	else:
		ctype = 'text/html'
		response_body = '''OK'''
		

	status = '200 OK'
	clientIP = os.environ['OPENSHIFT_PYTHON_IP']
	response_headers = [('Content-Type', ctype), ('Content-Length', str(len(response_body))), ('Access-Control-Allow-Credentials', 'false'), 
					('Access-Control-Allow-Origin', '*'), ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, PATCH, DELETE'), 
					]
	#
	start_response(status, response_headers)
	return [response_body]


import eventlet.wsgi
from flask import Flask, render_template


# app = Flask(__name__)
# 
# @app.after_request
# def headers(response):
# 	response.headers["Access-Control-Allow-Origin"] = "*"
# 	response.headers["Access-Control-Allow-Credentials"] = "false"
# 	return response
# 
# @app.route('/')
# def index():
# 	"""Serve the client-side application."""
# 	#return render_template('index.html')
# 	return "OK"
# 
# @io.on('connect', namespace='/chat')
# def connect(sid, environ):
# 	writeToLog("connect ", sid)
# 
# @io.on('chat message', namespace='/chat')
# def message(sid, data):
# 	writeToLog("message ", data)
# 	io.emit(sid, 'reply')
# 
# @io.on('disconnect', namespace='/chat')
# def disconnect(sid):
# 	writeToLog('disconnect ', sid)

if __name__ == '__main__':
	# wrap Flask application with engineio's middleware
	app = socketio.Middleware(io, app)

	# deploy as an eventlet WSGI server
	port = int(os.environ['OPENSHIFT_PYTHON_PORT'])
	eventlet.wsgi.server(eventlet.listen((os.environ['OPENSHIFT_PYTHON_IP'], port)), app)
	io.listen(app)
	writeToLog("Listening on port: "  + str(port))

#
# Below for testing only
#
# if __name__ == '__main__':
# 	from wsgiref.simple_server import make_server
# 	httpd = make_server('localhost', 3000, application)
# 	# Wait for a single request, serve it and quit.
# 	httpd.handle_request()


#writeToLog(makeId())
