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


class session:
	id = 0
	lastKnownTime = 0
	lastKnownTimeUpdatedAt = 0
	messages = []
	ownerId = ""
	state = 'paused'
	userIds = []
	videoId = 0

	def __init__(self, lastKnownTime, lastKnownTimeUpdatedAt, messages, ownerId, state, userIds, videoId):
		self.lastKnownTime = lastKnownTime
		self.lastKnownTimeUpdatedAt = lastKnownTimeUpdatedAt
		self.messages = messages
		self.ownerId = ownerId
		self.state = state
		self.userIds = userIds
		self.videoId = videoId


class user:

	def __init__(self, uId, sessionId, socket):
		self.id = uId
		self.sessionId = sessionId
		self.socket = socket
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
	return (dt - datetime.datetime(1970, 1, 1)).total_seconds()


#validation functions
def validateId(uId):
	return isinstance(id, basestring) and len(uId) == 16


def validateLastKnownTime(lastKnownTime):
	return isNumber(lastKnownTime) and lastKnownTime % 1 == 0 and lastKnownTime >= 0


def validateTimestamp(timestamp):
	validateLastKnownTime(timestamp)


def validateBoolean(boolean):
	isinstance(boolean, bool)


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

@io.on('connection')
def onConnection(socket):
	userId = makeId()
	users[userId] = user(userId, None, socket)
	socket.emit('userId', userId)
	logger.info('User ' + userId + ' connected.')
	
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
				logger.info('Sending presence to user ' + uId + '.')
				users[uId].socket.emit('setPresence', {'anyoneTyping': anyoneTyping})
				
	# precondition: user userId is in a session
	# precondition: body is a string
	# precondition: isSystemMessage is a boolean
	def sendMessage(body, isSystemMessage):
		message = dict(body = body, 
					isSystemMessage = isSystemMessage, 
					timestamp = datetime.now(), 
					userId = userId
					)
		sessions[users[userId].sessionId].messages.push(message)
		
		for userId in sessions[users[userId].sessionId].userIds:
			logger.info('Sending message to user' + userId + '.')
			users[userId].socket.emit('sendMessage', message)
			
	# precondition: user userId is in a session
	def leaveSession():
		sendMessage('left', True)
		
		sessionId = users[userId].sessionId
		
		sessions[sessionId].userIds.remove(userId)
		
		users[userId].sessionId = None
		
		
		if len(sessions[sessionId].userIds) == 0:
			del sessions[sessionId]
			logger.info('Session ' + sessionId + ' was deleted because there were no more users in it.')
		else:
			broadcastPresence(sessionId, None)
	
	@socket.on('reboot')
	def onReboot(data, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.'))
			return
		
		if (not validateId(data.sessionId)):
			fn(dict( errorMessage = 'Invalid session ID.' ))
			logger.info('User ' + userId + ' attempted to reboot invalid session ' + json.dump(data.sessionId) + '.')
			return
		
		if (not validateLastKnownTime(data.lastKnownTime)):
			fn(dict( errorMessage = 'Invalid lastKnownTime.' ))
			logger.info('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTime ' + json.dump(data.lastKnownTime) + '.')
			return
	
		if (not validateTimestamp(data.lastKnownTimeUpdatedAt)):
			fn(dict( errorMessage = 'Invalid lastKnownTimeUpdatedAt.' ))
			logger.info('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTimeUpdatedAt ' + json.dump(data.lastKnownTimeUpdatedAt) + '.')
			return
		
		if (not validateMessages(data.messages)):
			fn(dict( errorMessage = 'Invalid messages.' ))
			logger.info('User ' + userId + ' attempted to reboot session with invalid messages ' + json.dump(data.messages) + '.')
			return
		
		if (not data.ownerId == None and not validateId(data.ownerId)):
			fn(dict( errorMessage = 'Invalid ownerId.' ))
			logger.info('User ' + userId + ' attempted to reboot invalid ownerId ' + json.dump(data.ownerId) + '.')
			return
		
		if (not validateState(data.state)):
			fn(dict( errorMessage = 'Invalid state.' ))
			logger.info('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid state ' + json.dump(data.state) + '.')
			return
		
		if (not validateId(data.userId)):
			fn(dict( errorMessage = 'Invalid userId.' ))
			logger.info('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid userId ' + json.dump(data.userId) + '.')
			return
		
		if (not validateVideoId(data.videoId)):
			fn(dict( errorMessage = 'Invalid video ID.' ))
			logger.info('User ' + userId + ' attempted to reboot session with invalid video ' + json.dump(data.videoId) + '.')
			return
		
		if (not users[userId].sessionId == None):
			sessions[users[userId].sessionId].userIds.remove(userId)
			if (sessions[users[userId].sessionId].userIds.length == 0):
				del sessions[users[userId].sessionId]
		
		if (not userId == data.userId):
			users[data.userId] = users[userId]
			del users[userId]
			userId = data.userId
			
		if (sessions.count(data.sessionId) > 0):
			sessions[data.sessionId].userIds.push(userId)
			users[userId].sessionId = data.sessionId
			logger.info('User ' + userId + ' reconnected and rejoined session ' + users[userId].sessionId + '.')
		else:
			tempMessages = []
			for msg in data.messages:	
				tempMessages.append(dict(
									userId= msg.userId,
									body= msg.body,
									isSystemMessage= msg.isSystemMessage,
									timestamp= datetime.fromtimestamp(msg.timestamp)
									)
								)		
			session = dict(
					id = data.sessionId,
					lastKnownTime = data.lastKnownTime,
					lastKnownTimeUpdatedAt = datetime.fromtimestamp(data.lastKnownTimeUpdatedAt),

					messages = tempMessages,
					ownerId = data.ownerId,
					state = data.state,
					videoId = data.videoId,
					userIds = [userId]
					)
			sessions[session.id] = session
			users[userId].sessionId = data.sessionId
			logger.info('User ' + userId + ' rebooted session ' + users[userId].sessionId + ' with video ' + json.dump(data.videoId) + ', time ' + json.dump(data.lastKnownTime) + ', and state ' + data.state + ' for epoch ' + json.dump(data.lastKnownTimeUpdatedAt) + '.')
			
		fn(dict(
			lastKnownTime= sessions[data.sessionId].lastKnownTime,
			lastKnownTimeUpdatedAt= toTimestampSeconds(sessions[data.sessionId].lastKnownTimeUpdatedAt,
			state= sessions[data.sessionId].state
			)))
	
	@socket.on('createSession')
	def onCreateSession(data, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.log('The socket received a message after it was disconnected.')
			return
		
		if (not validateBoolean(data.controlLock)):
			fn(dict( errorMessage = 'Invalid controlLock.' ))
			logger.info('User ' + userId + ' attempted to create session with invalid controlLock ' + json.dump(data.controlLock) + '.')
			return
		
		if (not validateVideoId(data.videoId)):
			fn(dict( errorMessage = 'Invalid video ID.' ))
			logger.info('User ' + userId + ' attempted to create session with invalid video ' + json.dump(data.videoId) + '.')
			return
		
		users[userId].sessionId = makeId()
		now = datetime.now()
		
		theSession = session(users[userId].sessionId, 
							0, 
							now, 
							[], 
							userId if data.controlLock else None, 
							'paused', 
							[userId], 
							data.videoId
							)
		
		sessions[session.id] = theSession
		
		tempMessages = []
		for msg in sessions[users[userId].sessionId].messages:
			tempMessages.append(dict(body = msg.body,
									isSystemMessage = msg.isSystemMessage,
									timestamp = toTimestampSeconds(msg.timestamp),
									userId = msg.userId
									
									)
								)
		
		fn(dict(
			lastKnownTime = sessions[users[userId].sessionId].lastKnownTime,
			lastKnownTimeUpdatedAt = toTimestampSeconds(sessions[users[userId].sessionId].lastKnownTimeUpdatedAt),
			messages = tempMessages,
			sessionId = users[userId].sessionId,
			state = sessions[users[userId].sessionId].state
			)
		)
					
		if (data.controlLock):
			sendMessage('created the session with exclusive control', True)
		else:
			sendMessage('created the session', True)
		
		logger.info('User ' + userId + ' created session ' + users[userId].sessionId + ' with video ' + json.dump(data.videoId) + ' and controlLock ' + json.dump(data.controlLock) + '.')

	@socket.on('joinSession')
	def onJoinSession(sessionId, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.info('The socket received a message after it was disconnected.')
			return
		
		if (not validateId(sessionId) or not hasattr(sessions,sessionId)):
			fn(dict( errorMessage = 'Invalid session ID.' ))
			logger.info('User ' + userId + ' attempted to join nonexistent session ' + json.dump(sessionId) + '.')
			return
		
		if (not users[userId].sessionId == None):
			fn(dict( errorMessage = 'Already in a session.' ))
			logger.info('User ' + userId + ' attempted to join session ' + sessionId + ', but the user is already in session ' + users[userId].sessionId + '.')
			return
		
		users[userId].sessionId = sessionId
		sessions[sessionId].userIds.push(userId)
		sendMessage('joined', True)
		
		tempMessages = []
		for msg in sessions[sessionId].messages:
			tempMessages.append(dict(
									body = msg.body,
									isSystemMessage = msg.isSystemMessage,
									timestamp = toTimestampSeconds(msg.timestamp),
									userId = msg.userId)
							)
		
		fn(dict(
		videoId = sessions[sessionId].videoId,
		lastKnownTime = sessions[sessionId].lastKnownTime,
		lastKnownTimeUpdatedAt = sessions[sessionId].lastKnownTimeUpdatedAt.getTime(),
		messages = tempMessages,
		ownerId = sessions[sessionId].ownerId,
		state = sessions[sessionId].state
		))
		
		logger.info('User ' + userId + ' joined session ' + sessionId + '.')
		
	@socket.on('leaveSession')
	def onLeaveSession(_, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.info('The socket received a message after it was disconnected.')
			return
		
		if (users[userId].sessionId == None):
			fn(dict( errorMessage = 'Not in a session.' ))
			logger.info('User ' + userId + ' attempted to leave a session, but the user was not in one.')
			return
		
		sessionId = users[userId].sessionId
		leaveSession()
	
		fn(None)
		logger.info('User ' + userId + ' left session ' + sessionId + '.')
		
	@socket.on('updateSession')
	def onUpdateSession(data, fn):
		if (not userId in  users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.info('The socket received a message after it was disconnected.')
			return
		
		if (users[userId].sessionId == None):
			fn(dict( errorMessage = 'Not in a session.' ))
			logger.info('User ' + userId + ' attempted to update a session, but the user was not in one.')
			return
		
		if (not validateLastKnownTime(data.lastKnownTime)):
			fn(dict( errorMessage = 'Invalid lastKnownTime.' ))
			logger.info('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTime ' + json.dump(data.lastKnownTime) + '.')
			return
		
		if (not validateTimestamp(data.lastKnownTimeUpdatedAt)):
			fn(dict( errorMessage = 'Invalid lastKnownTimeUpdatedAt.' ))
			logger.info('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTimeUpdatedAt ' + json.dump(data.lastKnownTimeUpdatedAt) + '.')
			return
		
		if (not validateState(data.state)):
			fn(dict( errorMessage = 'Invalid state.' ))
			logger.info('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid state ' + json.dump(data.state) + '.')
			return
		
		if (not sessions[users[userId].sessionId].ownerId == None and not sessions[users[userId].sessionId].ownerId == userId):
			fn(dict( errorMessage = 'Session locked.' ))
			logger.info('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' but the session is locked by ' + sessions[users[userId].sessionId].ownerId + '.')
			return
		
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
			
		sessions[users[userId].sessionId].lastKnownTime = data.lastKnownTime
		sessions[users[userId].sessionId].lastKnownTimeUpdatedAt = datetime.fromtimestamp(data.lastKnownTimeUpdatedAt)
		sessions[users[userId].sessionId].state = data.state
		
		if (stateUpdated and timeUpdated):
			if (data.state == 'playing'):
				sendMessage('started playing the video at ' + timeStr, True)
			else:
				sendMessage('paused the video at ' + timeStr, True)
		elif (stateUpdated):
			if (data.state == 'playing'):
				sendMessage('started playing the video', True)
			else:
				sendMessage('paused the video', True)
		elif (timeUpdated):
			sendMessage('jumped to ' + timeStr, True)
			
		fn()
		logger.info('User ' + userId + ' updated session ' + users[userId].sessionId + ' with time ' + json.dump(data.lastKnownTime) + ' and state ' + data.state + ' for epoch ' + json.dump(data.lastKnownTimeUpdatedAt) + '.')
		
		for uId in sessions[users[userId].sessionId].userIds:
			logger.info('Sending update to user ' + uId + '.')
			if (not uId == userId):
				users[userId].socket.emit('update', dict(
													lastKnownTime = sessions[users[userId].sessionId].lastKnownTime,
													lastKnownTimeUpdatedAt = sessions[users[userId].sessionId].lastKnownTimeUpdatedAt.getTime(),
													state = sessions[users[userId].sessionId].state)
										)

	@socket.on('typing')
	def onTyping(data, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.info('The socket received a message after it was disconnected.')
			return
		
		if (users[userId].sessionId == None):
			fn(dict( errorMessage = 'Not in a session.' ))
			logger.info('User ' + userId + ' attempted to set presence, but the user was not in a session.')
			return
		
		if (not validateBoolean(data.typing)):
			fn(dict( errorMessage = 'Invalid typing.' ))
			logger.info('User ' + userId + ' attempted to set invalid presence ' + json.dump(data.typing) + '.')
			return
		
		users[userId].typing = data.typing
		
		fn()
		
		if (users[userId].typing):
			logger.info('User ' + userId + ' is typing...')
		else:
			logger.info('User ' + userId + ' is done typing.')
			
		broadcastPresence(users[userId].sessionId, userId)
		
	@socket.on('sendMessage')
	def onSendMessage(data, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.info('The socket received a message after it was disconnected.')
			return
		
		if (users[userId].sessionId == None):
			fn(dict( errorMessage = 'Not in a session.' ))
			logger.info('User ' + userId + ' attempted to send a message, but the user was not in a session.')
			return
		
		if (not validateMessageBody(data.body)):
			fn(dict( errorMessage = 'Invalid message body.' ))
			logger.info('User ' + userId + ' attempted to send an invalid message ' + json.dump(data.body) + '.')
			return
		
		sendMessage(data.body, False)
		fn()
		logger.info('User ' + userId + ' sent message ' + data.body + '.')
		
	@socket.on('getServerTime')
	def onGetServerTime(data, fn):
		if (not userId in users):
			fn(dict( errorMessage = 'Disconnected.' ))
			logger.info('The socket received a message after it was disconnected.')
			return
		
		fn(toTimestampSeconds(datetime.now()))
		if (data != None and isinstance(data.version, basestring)):
			logger.info('User ' + userId + ' pinged with version ' + data.version + '.')
		else:
			logger.info('User ' + userId + ' pinged.')
			
	@socket.on('disconnect')
	def onDisconnect():
		if (not userId in users):
			logger.info('The socket received a message after it was disconnected.')
			return
		if (users[userId].sessionId != None):
			leaveSession()
			
		del users[userId]
		logger.info('User ' + userId + ' disconnected.')
		
	@socket.on('error')
	def onError(e):
		logger.error(e)
		
#   server = http.listen(process.env.PORT || 3000, function() {
#   logger.info('Listening on port %d.', server.address().port);
# });
	
def application(environ, start_response):

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
	response_headers = [('Content-Type', ctype), ('Content-Length', str(len(response_body)))]
	#
	start_response(status, response_headers)
	return [response_body]

#
# Below for testing only
#
if __name__ == '__main__':
	from wsgiref.simple_server import make_server
	httpd = make_server('localhost', 3000, application)
	# Wait for a single request, serve it and quit.
	httpd.handle_request()


#print(makeId())
