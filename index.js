//////////////////////////////////////////////////////////////////////////
// Configuration                                                        //
//////////////////////////////////////////////////////////////////////////

// express
var express = require('express');
var app = express();

// socket.io
var http = require('http').Server(app);
var io = require('socket.io')(http);

// lodash
var lodash = require('lodash');

// request logging
var morgan = require('morgan');
app.use(morgan('short'));

// turn off unnecessary header
app.disable('x-powered-by');

// turn on strict routing
app.enable('strict routing');

// use the X-Forwarded-* headers
app.enable('trust proxy');

// add CORS headers
app.use(function(req, res, next) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, PATCH, DELETE');
  res.setHeader('Access-Control-Allow-Credentials', true);
  next();
});

//////////////////////////////////////////////////////////////////////////
// State                                                                //
//////////////////////////////////////////////////////////////////////////

// in-memory store of all the sessions
// the keys are the session IDs (strings)
// the values have the form: {
//   id: 'cba82ca5f59a35e6',                                                                // 8 random octets
//   lastKnownTime: 123,                                                                    // milliseconds from the start of the video
//   lastKnownTimeUpdatedAt: new Date(),                                                    // when we last received a time update
//   messages: [{ userId: '3d16d961f67e9792', body: 'hello', timestamp: new Date() }, ...], // the chat messages for this session
//   ownerId: '3d16d961f67e9792',                                                           // id of the session owner (if any)
//   state: 'playing' | 'paused',                                                           // whether the video is playing or paused
//   userIds: ['3d16d961f67e9792', ...],                                                    // ids of the users in the session
//   videoId: 123                                                                           // Netflix id the video
// }
var sessions = {};

// in-memory store of all the users
// the keys are the user IDs (strings)
// the values have the form: {
//   id: '3d16d961f67e9792',        // 8 random octets
//   sessionId: 'cba82ca5f59a35e6', // id of the session, if one is joined
//   socket: <websocket>,           // the websocket
//   typing: false                  // whether the user is typing or not
// }
var users = {};

// generate a random ID with 64 bits of entropy
function makeId() {
  var result = '';
  var hexChars = '0123456789abcdef';
  for (var i = 0; i < 16; i += 1) {
    result += hexChars[Math.floor(Math.random() * 16)];
  }
  return result;
}

//////////////////////////////////////////////////////////////////////////
// Web endpoints                                                        //
//////////////////////////////////////////////////////////////////////////

// health check
app.get('/', function(req, res) {
  res.setHeader('Content-Type', 'text/plain');
  res.send('OK');
});

// number of sessions
app.get('/number-of-sessions', function(req, res) {
  res.setHeader('Content-Type', 'text/plain');
  res.send(String(Object.keys(sessions).length));
});

// number of users
app.get('/number-of-users', function(req, res) {
  res.setHeader('Content-Type', 'text/plain');
  res.send(String(Object.keys(users).length));
});

//////////////////////////////////////////////////////////////////////////
// Websockets API                                                       //
//////////////////////////////////////////////////////////////////////////

function validateId(id) {
  return typeof id === 'string' && id.length === 16;
}

function validateLastKnownTime(lastKnownTime) {
  return typeof lastKnownTime === 'number' &&
    lastKnownTime % 1 === 0 &&
    lastKnownTime >= 0;
}

function validateTimestamp(timestamp) {
  return typeof timestamp === 'number' &&
    timestamp % 1 === 0 &&
    timestamp >= 0;
}

function validateBoolean(boolean) {
  return typeof boolean === 'boolean';
}

function validateMessages(messages) {
  if (typeof messages !== 'object' || messages === null || typeof messages.length !== 'number') {
    return false;
  }
  for (var i in messages) {
    if (messages.hasOwnProperty(i)) {
      i = parseInt(i);
      if (isNaN(i)) {
        return false;
      }
      if (typeof i !== 'number' || i % 1 !== 0 || i < 0 || i >= messages.length) {
        return false;
      }
      if (typeof messages[i] !== 'object' || messages[i] === null) {
        return false;
      }
      if (!validateMessageBody(messages[i].body)) {
        return false;
      }
      if (messages[i].isSystemMessage === undefined) {
        messages[i].isSystemMessage = false;
      }
      if (!validateBoolean(messages[i].isSystemMessage)) {
        return false;
      }
      if (!validateTimestamp(messages[i].timestamp)) {
        return false;
      }
      if (!validateId(messages[i].userId)) {
        return false;
      }
    }
  }
  return true;
}

function validateState(state) {
  return typeof state === 'string' && (state === 'playing' || state === 'paused');
}

function validateVideoId(videoId) {
  return typeof videoId === 'number' && videoId % 1 === 0 && videoId >= 0;
}

function validateMessageBody(body) {
  return typeof body === 'string' && body.replace(/^\s+|\s+$/g, '') !== '';
}

function padIntegerWithZeros(x, minWidth) {
  var numStr = String(x);
  while (numStr.length < minWidth) {
    numStr = '0' + numStr;
  }
  return numStr;
}

io.on('connection', function(socket) {
  var userId = makeId();
  users[userId] = {
    id: userId,
    sessionId: null,
    socket: socket,
    typing: false
  };
  socket.emit('userId', userId);
  console.log('User ' + userId + ' connected.');

  // precondition: sessionId is the id of a session
  // precondition: notToThisUserId is the id of a user, or null
  var broadcastPresence = function(sessionId, notToThisUserId) {
    var anyoneTyping = false;
    for (var i = 0; i < sessions[sessionId].userIds.length; i += 1) {
      if (users[sessions[sessionId].userIds[i]].typing) {
        anyoneTyping = true;
        break;
      }
    }

    lodash.forEach(sessions[sessionId].userIds, function(id) {
      if (id !== notToThisUserId) {
        console.log('Sending presence to user ' + id + '.');
        users[id].socket.emit('setPresence', {
          anyoneTyping: anyoneTyping
        });
      }
    });
  };

  // precondition: user userId is in a session
  // precondition: body is a string
  // precondition: isSystemMessage is a boolean
  var sendMessage = function(body, isSystemMessage) {
    var message = {
      body: body,
      isSystemMessage: isSystemMessage,
      timestamp: new Date(),
      userId: userId
    };
    sessions[users[userId].sessionId].messages.push(message);

    lodash.forEach(sessions[users[userId].sessionId].userIds, function(id) {
      console.log('Sending message to user ' + id + '.');
      users[id].socket.emit('sendMessage', {
        body: message.body,
        isSystemMessage: isSystemMessage,
        timestamp: message.timestamp.getTime(),
        userId: message.userId
      });
    });
  };

  // precondition: user userId is in a session
  var leaveSession = function() {
    sendMessage('left', true);

    var sessionId = users[userId].sessionId;
    lodash.pull(sessions[sessionId].userIds, userId);
    users[userId].sessionId = null;

    if (sessions[sessionId].userIds.length === 0) {
      delete sessions[sessionId];
      console.log('Session ' + sessionId + ' was deleted because there were no more users in it.');
    } else {
      broadcastPresence(sessionId, null);
    }
  };

  socket.on('reboot', function(data, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (!validateId(data.sessionId)) {
      fn({ errorMessage: 'Invalid session ID.' });
      console.log('User ' + userId + ' attempted to reboot invalid session ' + JSON.stringify(data.sessionId) + '.');
      return;
    }

    if (!validateLastKnownTime(data.lastKnownTime)) {
      fn({ errorMessage: 'Invalid lastKnownTime.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTime ' + JSON.stringify(data.lastKnownTime) + '.');
      return;
    }

    if (!validateTimestamp(data.lastKnownTimeUpdatedAt)) {
      fn({ errorMessage: 'Invalid lastKnownTimeUpdatedAt.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTimeUpdatedAt ' + JSON.stringify(data.lastKnownTimeUpdatedAt) + '.');
      return;
    }

    if (!validateMessages(data.messages)) {
      fn({ errorMessage: 'Invalid messages.' });
      console.log('User ' + userId + ' attempted to reboot session with invalid messages ' + JSON.stringify(data.messages) + '.');
      return;
    }

    if (data.ownerId !== null && !validateId(data.ownerId)) {
      fn({ errorMessage: 'Invalid ownerId.' });
      console.log('User ' + userId + ' attempted to reboot invalid ownerId ' + JSON.stringify(data.ownerId) + '.');
      return;
    }

    if (!validateState(data.state)) {
      fn({ errorMessage: 'Invalid state.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid state ' + JSON.stringify(data.state) + '.');
      return;
    }

    if (!validateId(data.userId)) {
      fn({ errorMessage: 'Invalid userId.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid userId ' + JSON.stringify(data.userId) + '.');
      return;
    }

    if (!validateVideoId(data.videoId)) {
      fn({ errorMessage: 'Invalid video ID.' });
      console.log('User ' + userId + ' attempted to reboot session with invalid video ' + JSON.stringify(data.videoId) + '.');
      return;
    }

    if (users[userId].sessionId !== null) {
      lodash.pull(sessions[users[userId].sessionId].userIds, userId);
      if (sessions[users[userId].sessionId].userIds.length === 0) {
        delete sessions[users[userId].sessionId];
      }
    }
    if (userId !== data.userId) {
      users[data.userId] = users[userId];
      delete users[userId];
      userId = data.userId;
    }

    if (sessions.hasOwnProperty(data.sessionId)) {
      sessions[data.sessionId].userIds.push(userId);
      users[userId].sessionId = data.sessionId;
      console.log('User ' + userId + ' reconnected and rejoined session ' + users[userId].sessionId + '.');
    } else {
      var session = {
        id: data.sessionId,
        lastKnownTime: data.lastKnownTime,
        lastKnownTimeUpdatedAt: new Date(data.lastKnownTimeUpdatedAt),
        messages: lodash.map(data.messages, function(message) { return {
          userId: message.userId,
          body: message.body,
          isSystemMessage: message.isSystemMessage,
          timestamp: new Date(message.timestamp)
        }; }),
        ownerId: data.ownerId,
        state: data.state,
        videoId: data.videoId,
        userIds: [userId]
      };
      sessions[session.id] = session;
      users[userId].sessionId = data.sessionId;
      console.log('User ' + userId + ' rebooted session ' + users[userId].sessionId + ' with video ' + JSON.stringify(data.videoId) + ', time ' + JSON.stringify(data.lastKnownTime) + ', and state ' + data.state + ' for epoch ' + JSON.stringify(data.lastKnownTimeUpdatedAt) + '.');
    }

    fn({
      lastKnownTime: sessions[data.sessionId].lastKnownTime,
      lastKnownTimeUpdatedAt: sessions[data.sessionId].lastKnownTimeUpdatedAt.getTime(),
      state: sessions[data.sessionId].state
    });
  });

  socket.on('createSession', function(data, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (!validateBoolean(data.controlLock)) {
      fn({ errorMessage: 'Invalid controlLock.' });
      console.log('User ' + userId + ' attempted to create session with invalid controlLock ' + JSON.stringify(data.controlLock) + '.');
      return;
    }

    if (!validateVideoId(data.videoId)) {
      fn({ errorMessage: 'Invalid video ID.' });
      console.log('User ' + userId + ' attempted to create session with invalid video ' + JSON.stringify(data.videoId) + '.');
      return;
    }

    users[userId].sessionId = makeId();
    var now = new Date();
    var session = {
      id: users[userId].sessionId,
      lastKnownTime: 0,
      lastKnownTimeUpdatedAt: now,
      messages: [],
      ownerId: data.controlLock ? userId : null,
      state: 'paused',
      userIds: [userId],
      videoId: data.videoId
    };
    sessions[session.id] = session;

    fn({
      lastKnownTime: sessions[users[userId].sessionId].lastKnownTime,
      lastKnownTimeUpdatedAt: sessions[users[userId].sessionId].lastKnownTimeUpdatedAt.getTime(),
      messages: lodash.map(sessions[users[userId].sessionId].messages, function(message) { return {
        body: message.body,
        isSystemMessage: message.isSystemMessage,
        timestamp: message.timestamp.getTime(),
        userId: message.userId
      }; }),
      sessionId: users[userId].sessionId,
      state: sessions[users[userId].sessionId].state
    });
    if (data.controlLock) {
      sendMessage('created the session with exclusive control', true);
    } else {
      sendMessage('created the session', true);
    }
    console.log('User ' + userId + ' created session ' + users[userId].sessionId + ' with video ' + JSON.stringify(data.videoId) + ' and controlLock ' + JSON.stringify(data.controlLock) + '.');
  });

  socket.on('joinSession', function(sessionId, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (!validateId(sessionId) || !sessions.hasOwnProperty(sessionId)) {
      fn({ errorMessage: 'Invalid session ID.' });
      console.log('User ' + userId + ' attempted to join nonexistent session ' + JSON.stringify(sessionId) + '.');
      return;
    }

    if (users[userId].sessionId !== null) {
      fn({ errorMessage: 'Already in a session.' });
      console.log('User ' + userId + ' attempted to join session ' + sessionId + ', but the user is already in session ' + users[userId].sessionId + '.');
      return;
    }

    users[userId].sessionId = sessionId;
    sessions[sessionId].userIds.push(userId);
    sendMessage('joined', true);

    fn({
      videoId: sessions[sessionId].videoId,
      lastKnownTime: sessions[sessionId].lastKnownTime,
      lastKnownTimeUpdatedAt: sessions[sessionId].lastKnownTimeUpdatedAt.getTime(),
      messages: lodash.map(sessions[sessionId].messages, function(message) { return {
        body: message.body,
        isSystemMessage: message.isSystemMessage,
        timestamp: message.timestamp.getTime(),
        userId: message.userId
      }; }),
      ownerId: sessions[sessionId].ownerId,
      state: sessions[sessionId].state
    });
    console.log('User ' + userId + ' joined session ' + sessionId + '.');
  });

  socket.on('leaveSession', function(_, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (users[userId].sessionId === null) {
      fn({ errorMessage: 'Not in a session.' });
      console.log('User ' + userId + ' attempted to leave a session, but the user was not in one.');
      return;
    }

    var sessionId = users[userId].sessionId;
    leaveSession();

    fn(null);
    console.log('User ' + userId + ' left session ' + sessionId + '.');
  });

  socket.on('updateSession', function(data, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (users[userId].sessionId === null) {
      fn({ errorMessage: 'Not in a session.' });
      console.log('User ' + userId + ' attempted to update a session, but the user was not in one.');
      return;
    }

    if (!validateLastKnownTime(data.lastKnownTime)) {
      fn({ errorMessage: 'Invalid lastKnownTime.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTime ' + JSON.stringify(data.lastKnownTime) + '.');
      return;
    }

    if (!validateTimestamp(data.lastKnownTimeUpdatedAt)) {
      fn({ errorMessage: 'Invalid lastKnownTimeUpdatedAt.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTimeUpdatedAt ' + JSON.stringify(data.lastKnownTimeUpdatedAt) + '.');
      return;
    }

    if (!validateState(data.state)) {
      fn({ errorMessage: 'Invalid state.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid state ' + JSON.stringify(data.state) + '.');
      return;
    }

    if (sessions[users[userId].sessionId].ownerId !== null && sessions[users[userId].sessionId].ownerId !== userId) {
      fn({ errorMessage: 'Session locked.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' but the session is locked by ' + sessions[users[userId].sessionId].ownerId + '.');
      return;
    }

    var now = (new Date()).getTime();
    var oldPredictedTime = sessions[users[userId].sessionId].lastKnownTime +
      (sessions[users[userId].sessionId].state === 'paused' ? 0 : (
        now - sessions[users[userId].sessionId].lastKnownTimeUpdatedAt.getTime()
      ));
    var newPredictedTime = data.lastKnownTime +
      (data.state === 'paused' ? 0 : (
        now - data.lastKnownTimeUpdatedAt
      ));

    var stateUpdated = sessions[users[userId].sessionId].state !== data.state;
    var timeUpdated = Math.abs(newPredictedTime - oldPredictedTime) > 2500;

    var hours = Math.floor(newPredictedTime / (1000 * 60 * 60));
    newPredictedTime -= hours * 1000 * 60 * 60;
    var minutes = Math.floor(newPredictedTime / (1000 * 60));
    newPredictedTime -= minutes * 1000 * 60;
    var seconds = Math.floor(newPredictedTime / 1000);
    newPredictedTime -= seconds * 1000;

    var timeStr;
    if (hours > 0) {
      timeStr = String(hours) + ':' + String(minutes) + ':' + padIntegerWithZeros(seconds, 2);
    } else {
      timeStr = String(minutes) + ':' + padIntegerWithZeros(seconds, 2);
    }

    sessions[users[userId].sessionId].lastKnownTime = data.lastKnownTime;
    sessions[users[userId].sessionId].lastKnownTimeUpdatedAt = new Date(data.lastKnownTimeUpdatedAt);
    sessions[users[userId].sessionId].state = data.state;

    if (stateUpdated && timeUpdated) {
      if (data.state === 'playing') {
        sendMessage('started playing the video at ' + timeStr, true);
      } else {
        sendMessage('paused the video at ' + timeStr, true);
      }
    } else if (stateUpdated) {
      if (data.state === 'playing') {
        sendMessage('started playing the video', true);
      } else {
        sendMessage('paused the video', true);
      }
    } else if (timeUpdated) {
      sendMessage('jumped to ' + timeStr, true);
    }

    fn();
    console.log('User ' + userId + ' updated session ' + users[userId].sessionId + ' with time ' + JSON.stringify(data.lastKnownTime) + ' and state ' + data.state + ' for epoch ' + JSON.stringify(data.lastKnownTimeUpdatedAt) + '.');

    lodash.forEach(sessions[users[userId].sessionId].userIds, function(id) {
      if (id !== userId) {
        console.log('Sending update to user ' + id + '.');
        users[id].socket.emit('update', {
          lastKnownTime: sessions[users[userId].sessionId].lastKnownTime,
          lastKnownTimeUpdatedAt: sessions[users[userId].sessionId].lastKnownTimeUpdatedAt.getTime(),
          state: sessions[users[userId].sessionId].state
        });
      }
    });
  });

  socket.on('typing', function(data, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (users[userId].sessionId === null) {
      fn({ errorMessage: 'Not in a session.' });
      console.log('User ' + userId + ' attempted to set presence, but the user was not in a session.');
      return;
    }

    if (!validateBoolean(data.typing)) {
      fn({ errorMessage: 'Invalid typing.' });
      console.log('User ' + userId + ' attempted to set invalid presence ' + JSON.stringify(data.typing) + '.');
      return;
    }

    users[userId].typing = data.typing;

    fn();
    if (users[userId].typing) {
      console.log('User ' + userId + ' is typing...');
    } else {
      console.log('User ' + userId + ' is done typing.');
    }

    broadcastPresence(users[userId].sessionId, userId);
  });

  socket.on('sendMessage', function(data, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (users[userId].sessionId === null) {
      fn({ errorMessage: 'Not in a session.' });
      console.log('User ' + userId + ' attempted to send a message, but the user was not in a session.');
      return;
    }

    if (!validateMessageBody(data.body)) {
      fn({ errorMessage: 'Invalid message body.' });
      console.log('User ' + userId + ' attempted to send an invalid message ' + JSON.stringify(data.body) + '.');
      return;
    }

    sendMessage(data.body, false);

    fn();
    console.log('User ' + userId + ' sent message ' + data.body + '.');
  });

  socket.on('getServerTime', function(data, fn) {
    if (!users.hasOwnProperty(userId)) {
      fn({ errorMessage: 'Disconnected.' });
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    fn((new Date()).getTime());
    if (typeof data === 'object' && data !== null && typeof data.version === 'string') {
      console.log('User ' + userId + ' pinged with version ' + data.version + '.');
    } else {
      console.log('User ' + userId + ' pinged.');
    }
  });

  socket.on('disconnect', function() {
    if (!users.hasOwnProperty(userId)) {
      console.log('The socket received a message after it was disconnected.');
      return;
    }

    if (users[userId].sessionId !== null) {
      leaveSession();
    }
    delete users[userId];
    console.log('User ' + userId + ' disconnected.');
  });

  socket.on('error', function(e) {
    console.error(e);
  });
});

var server = http.listen(process.env.PORT || 3000, function() {
  console.log('Listening on port %d.', server.address().port);
});
