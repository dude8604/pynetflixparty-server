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

io = socketio.Server(logger=True)

# generate a random ID with 64 bits of entropy


def makeId():
	result = ''
	hexChars = '0123456789abcdef'
	for i in xrange(0, len(hexChars)):
		result += hexChars[random.randint(0, len(hexChars) - 1)]

	return result


def isNumber(number):
	return isinstance(number, (int, long, float, complex)) and not isinstance(number, bool)


def toTimestampMilliseconds(dt):
	return (dt - datetime(1970, 1, 1)).total_seconds() * 1000


#validation functions
def validateId(uId):
	return isinstance(uId, basestring)


def validateLastKnownTime(lastKnownTime):
	if isNumber(lastKnownTime) and lastKnownTime % 1 == 0 and lastKnownTime >= 0:
		return True
	return False


def validateTimestamp(timestamp):
	return validateLastKnownTime(timestamp)


def validateBoolean(b):
	return (str(b).lower() == 'true' or str(b).lower() == 'false')


def validateMessages(messages):
	if (messages == None):
		return False

	for msg in messages:

		if (not isclass(msg) or msg == None):
			return False

		if (not validateMessageBody(msg['body'])):
			return False

		if (msg['isSystemMessage'] == None):
			msg['isSystemMessage'] = False

		if (not validateBoolean(msg['isSystemMessage'])):
			return False

		if (not validateTimestamp(msg['timestamp'])):
			return False
		
		if (not validateId(msg['userId'])):
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
				timestamp = toTimestampMilliseconds(datetime.now()), 
				userId = userId
				)
	sessions[users[userId].sessionId].messages.append(message)
	
	for uId in sessions[users[userId].sessionId].userIds:
		writeToLog('Sending message to user' + uId + ': ' + json.dumps(message))
		io.emit('sendMessage', message, uId)
		
# precondition: user userId is in a session
def leaveSession(userId):
	
	
	sessionId = users[userId].sessionId
	
	sessions[sessionId].userIds.remove(userId)
	sendMessage('left', True, userId)
	
	users[userId].sessionId = None
	
	
	if len(sessions[sessionId].userIds) == 0:
		del sessions[sessionId]
		writeToLog('Session ' + sessionId + ' was deleted because there were no more users in it.')
	else:
		broadcastPresence(sessionId, None)

@io.on('reboot')
def onReboot(sid, data):
	userId = sid
	writeToLog("reboot event received")
	if (not userId in users):
		return dict( errorMessage = 'Disconnected.')
	
	if (not validateId(data['sessionId'])):
		writeToLog('User ' + userId + ' attempted to reboot invalid session ' + json.dumps(data['sessionId']) + '.')
		return dict( errorMessage = 'Invalid session ID.' )
	
	if (not validateLastKnownTime(data['lastKnownTime'])):
		writeToLog('User ' + userId + ' attempted to reboot session ' + data['sessionId'] + ' with invalid lastKnownTime ' + json.dumps(data['lastKnownTime']) + '.')
		return dict( errorMessage = 'Invalid lastKnownTime.' )
	
	if (not validateTimestamp(data['lastKnownTimeUpdatedAt'])):
		writeToLog('User ' + userId + ' attempted to reboot session ' + data['sessionId'] + ' with invalid lastKnownTimeUpdatedAt ' + json.dumps(data['lastKnownTimeUpdatedAt']) + '.')
		return dict( errorMessage = 'Invalid lastKnownTimeUpdatedAt.' )
	
	if (not validateMessages(data['messages'])):
		writeToLog('User ' + userId + ' attempted to reboot session with invalid messages ' + json.dumps(data['messages']) + '.')
		return dict( errorMessage = 'Invalid messages.' )
	
	if (not data['ownerId'] == None and not validateId(data['ownerId'])):
		writeToLog('User ' + userId + ' attempted to reboot invalid ownerId ' + json.dumps(data['ownerId']) + '.')
		return dict( errorMessage = 'Invalid ownerId.' )
	
	if (not validateState(data['state'])):
		writeToLog('User ' + userId + ' attempted to reboot session ' + data['sessionId'] + ' with invalid state ' + json.dumps(data['state']) + '.')
		return dict( errorMessage = 'Invalid state.' )
	
	if (not validateId(data['userId'])):
		writeToLog('User ' + userId + ' attempted to reboot session ' + data['sessionId'] + ' with invalid userId ' + json.dumps(data['userId']) + '.')
		return dict( errorMessage = 'Invalid userId.' )
	
	if (not validateVideoId(data['videoId'])):
		writeToLog('User ' + userId + ' attempted to reboot session with invalid video ' + json.dumps(data['videoId']) + '.')
		return dict( errorMessage = 'Invalid video ID.' )
	
	if (users[userId].sessionId != None):
		sessions[users[userId].sessionId].userIds.remove(userId)
		if (sessions[users[userId].sessionId].userIds.length == 0):
			del sessions[users[userId].sessionId]
	
	if (userId != data['userId']):
		users[data['userId']] = users[userId]
		del users[userId]
		userId = data['userId']
		
	if (data['sessionId'] in sessions):
		sessions[data['sessionId']].userIds.append(userId)
		users[userId].sessionId = data['sessionId']
		writeToLog('User ' + userId + ' reconnected and rejoined session ' + users[userId].sessionId + '.')
	else:
		tempMessages = []
		for msg in data['messages']:	
			tempMessages.append(dict(
								userId= msg['userId'],
								body= msg['body'],
								isSystemMessage= msg['isSystemMessage'],
								timestamp= msg['timestamp']
								)
							)		
		session = dict(
				id = data['sessionId'],
				lastKnownTime = data['lastKnownTime'],
				lastKnownTimeUpdatedAt = data['lastKnownTimeUpdatedAt'],
				messages = tempMessages,
				ownerId = data['ownerId'],
				state = data['state'],
				videoId = data['videoId'],
				userIds = [userId]
				)
		sessions[session.id] = session
		users[userId].sessionId = data['sessionId']
		writeToLog('User ' + userId + ' rebooted session ' + users[userId].sessionId + ' with video ' + json.dumps(data['videoId']) + ', time ' + json.dumps(data['lastKnownTime']) + ', and state ' + data['state'] + ' for epoch ' + json.dumps(data['lastKnownTimeUpdatedAt']) + '.')
		
	return dict(
		lastKnownTime= sessions[data['sessionId']].lastKnownTime,
		lastKnownTimeUpdatedAt= sessions[data['sessionId']].lastKnownTimeUpdatedAt,
		state= sessions[data['sessionId']].state
		)
	
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
	now = toTimestampMilliseconds(datetime.now())
	
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
								timestamp = msg['timestamp'],
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
		lastKnownTimeUpdatedAt = sessions[users[userId].sessionId].lastKnownTimeUpdatedAt,
		messages = tempMessages,
		sessionId = users[userId].sessionId,
		state = sessions[users[userId].sessionId].state
		)
	

@io.on('joinSession')
def onJoinSession(sid, data):
	userId = sid
	sessionId = data
	if (not userId in users):
		writeToLog('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (not validateId(sessionId) or not sessionId in sessions):
		writeToLog('User ' + userId + ' attempted to join nonexistent session ' + json.dumps(sessionId) + '.')
		return dict( errorMessage = 'Invalid session ID.' )
	
	if (not users[userId].sessionId == None):
		writeToLog('User ' + userId + ' attempted to join session ' + sessionId + ', but the user is already in session ' + users[userId].sessionId + '.')
		return dict( errorMessage = 'Already in a session.' )
	
	users[userId].sessionId = sessionId
	sessions[sessionId].userIds.append(userId)
	sendMessage('joined', True, userId)
	
	tempMessages = []
	for msg in sessions[sessionId].messages:
		tempMessages.append(dict(
								body = msg['body'],
								isSystemMessage = msg['isSystemMessage'],
								timestamp = msg['timestamp'],
								userId = msg['userId']
								)
						)
	
	writeToLog('User ' + userId + ' joined session ' + sessionId + '.')	
	
	return dict(
	videoId = sessions[sessionId].videoId,
	lastKnownTime = sessions[sessionId].lastKnownTime,
	lastKnownTimeUpdatedAt = sessions[sessionId].lastKnownTimeUpdatedAt,
	messages = tempMessages,
	ownerId = sessions[sessionId].ownerId,
	state = sessions[sessionId].state
	)
	

	
@io.on('leaveSession')
def onLeaveSession(sid, data):
	userId = sid
	if (not userId in users):
		writeToLog('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (users[userId].sessionId == None):
		writeToLog('User ' + userId + ' attempted to leave a session, but the user was not in one.')
		return dict( errorMessage = 'Not in a session.' )
	
	sessionId = users[userId].sessionId
	leaveSession(userId)

	writeToLog('User ' + userId + ' left session ' + sessionId + '.')
	return tuple()
	
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
	
	if (sessions[users[userId].sessionId].ownerId != None and sessions[users[userId].sessionId].ownerId != userId):
		writeToLog('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' but the session is locked by ' + sessions[users[userId].sessionId].ownerId + '.')
		return dict( errorMessage = 'Session locked.' )
	
	intLastKnownTimeUpdatedAt = int(data['lastKnownTimeUpdatedAt'])
	intLastKnownTime = int(data['lastKnownTime'])
	now = toTimestampMilliseconds(datetime.now())
	oldPredictedTime = sessions[users[userId].sessionId].lastKnownTime + \
	(0 if sessions[users[userId].sessionId].state == 'paused' else (
																now - sessions[users[userId].sessionId].lastKnownTimeUpdatedAt
																))
	
	newPredictedTime = intLastKnownTime + \
	(0 if data['state'] == 'paused' else (now - intLastKnownTimeUpdatedAt))
	
	stateUpdated = sessions[users[userId].sessionId].state != data['state']
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
		
	sessions[users[userId].sessionId].lastKnownTime = intLastKnownTime
	sessions[users[userId].sessionId].lastKnownTimeUpdatedAt = intLastKnownTimeUpdatedAt
	sessions[users[userId].sessionId].state = data['state']
	
	if (stateUpdated and timeUpdated):
		if (data['state'] == 'playing'):
			sendMessage('started playing the video at ' + timeStr, True, userId)
		else:
			sendMessage('paused the video at ' + timeStr, True, userId)
	elif (stateUpdated):
		if (data['state'] == 'playing'):
			sendMessage('started playing the video', True, userId)
		else:
			sendMessage('paused the video', True, userId)
	elif (timeUpdated):
		sendMessage('jumped to ' + timeStr, True, userId)
		
	writeToLog('User ' + userId + ' updated session ' + users[userId].sessionId + ' with time ' + json.dumps(data['lastKnownTime']) + ' and state ' + data['state'] + ' for epoch ' + json.dumps(data['lastKnownTimeUpdatedAt']) + '.')
	writeToLog('users: ' + str(sessions[users[userId].sessionId].userIds))
	for uId in sessions[users[userId].sessionId].userIds:
		if (uId != userId):
			writeToLog('Sending update to user ' + uId + '.')			
			io.emit('update', dict(
												lastKnownTime = sessions[users[userId].sessionId].lastKnownTime,
												lastKnownTimeUpdatedAt = sessions[users[userId].sessionId].lastKnownTimeUpdatedAt,
												state = sessions[users[userId].sessionId].state),
												users[uId].id
									)
		else:
			writeToLog('NOT Sending update to user ' + uId + '.')	
	return tuple()
# 
@io.on('typing')
def onTyping(sid, data):
	userId = sid
	if (not userId in users):
		writeToLog('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (users[userId].sessionId == None):
		writeToLog('User ' + userId + ' attempted to set presence, but the user was not in a session.')
		return dict( errorMessage = 'Not in a session.' )
	
	if (not validateBoolean(data['typing'])):
		writeToLog('User ' + userId + ' attempted to set invalid presence ' + json.dumps(data['typing']) + '.')
		return dict( errorMessage = 'Invalid typing.' )
	
	users[userId].typing = data['typing']
	
	if (users[userId].typing):
		writeToLog('User ' + userId + ' is typing...')
	else:
		writeToLog('User ' + userId + ' is done typing.')
		
	broadcastPresence(users[userId].sessionId, userId)
	
	return tuple()
	
	
@io.on('sendMessage')
def onSendMessage(sid, data):
	userId = sid
	if (not userId in users):
		writeToLog('The socket received a message after it was disconnected.')
		return dict( errorMessage = 'Disconnected.' )
	
	if (users[userId].sessionId == None):
		writeToLog('User ' + userId + ' attempted to send a message, but the user was not in a session.')
		return dict( errorMessage = 'Not in a session.' )
	
	if (not validateMessageBody(data['body'])):
		writeToLog('User ' + userId + ' attempted to send an invalid message ' + json.dumps(data['body']) + '.')
		return dict( errorMessage = 'Invalid message body.' )
	
	sendMessage(data['body'], False, userId)

	writeToLog('User ' + userId + ' sent message ' + data['body'] + '.')
	
	return tuple()
	
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
		
	return toTimestampMilliseconds(datetime.now())
		
@io.on('disconnect')
def onDisconnect(sid):
	if (not sid in users):
		writeToLog('The socket received a message after it was disconnected.')
		return
	if (users[sid].sessionId != None):
		leaveSession(sid)
		
	del users[sid]
	writeToLog('User ' + sid + ' disconnected.')
	
	return tuple()
	
@io.on('error')
def onError(e):
	writeToLog(e)
		
#   server = http.listen(process.env.PORT || 3000, function() {
#   writeToLog('Listening on port %d.', server.address().port);
# });
	
def sessionsToHTML():
	html = '<p><h3>Active Sessions:</h3></p>'
	
	for sId, sess in sessions.iteritems():
		html += '<p><b>Session: ' + sId + '</b><br />'
		html += 'id: ' + sess.id + '<br />'
		html += 'lastKnownTime: ' + str(sess.lastKnownTime) + '<br />'
		html += 'lastKnownTimeUpdatedAt: ' + str(sess.lastKnownTimeUpdatedAt) + '<br />'
		html += 'messages: ' + str(sess.messages) + '<br />'
		html += 'ownerId: ' + str(sess.ownerId) + '<br />'
		html += 'userIds: ' + str(sess.userIds) + '<br />'
		html += 'videoId: ' + str(sess.videoId) + '<br />'
		html += '</p>'
		
	return html
		
	
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
	elif pathInfo == '/sessions':
		ctype = 'text/html'
		response_body = sessionsToHTML()
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


if __name__ == '__main__':
	# wrap wsgi application with engineio's middleware
	app = socketio.Middleware(io, app)

	# deploy as an eventlet WSGI server
	port = int(os.environ['OPENSHIFT_PYTHON_PORT'])
	eventlet.wsgi.server(eventlet.listen((os.environ['OPENSHIFT_PYTHON_IP'], port)), app)
	io.listen(app)
	writeToLog("Listening on port: "  + str(port))
	
	