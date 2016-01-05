// we don't use HTTPS (WSS) here because CloudFlare (our CDN) only supports
// websockets for "enterprise" customers. so for now we use HTTP (WS) and
// bypass CloudFlare.

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

// generate UUIDs
var uuid = require('node-uuid');

function makeId() {
  return uuid.v4().replace(/-/g, '').substr(16);
}

//////////////////////////////////////////////////////////////////////////
// State                                                                //
//////////////////////////////////////////////////////////////////////////

// in-memory store of all the sessions
// the keys are the session IDs (strings)
// the values have the form: {
//   id: '84dba68dcea2952c',             // 8 random octets
//   lastKnownTime: 123,                 // milliseconds from the start of the video
//   lastKnownTimeUpdatedAt: new Date(), // when we last received a time update
//   state: 'playing' | 'paused',        // whether the video is playing or paused
//   userIds: ['9a3078cd522cc3ff', ...]  // ids of the users in the session
//   videoId: 123                        // Netflix id the video
// }
var sessions = {};

// in-memory store of all the users
// the keys are the user IDs (strings)
// the values have the form: {
//   id: '9a3078cd522cc3ff',        // 8 random octets
//   sessionId: '84dba68dcea2952c', // id of the session, if one is joined
//   socket: <websocket>            // the websocket
// }
var users = {};

//////////////////////////////////////////////////////////////////////////
// Web endpoints                                                        //
//////////////////////////////////////////////////////////////////////////

// landing page
app.get('/', function(req, res) {
  res.send('This is the server for Netflix Party.');
});

//////////////////////////////////////////////////////////////////////////
// Websockets API                                                       //
//////////////////////////////////////////////////////////////////////////

io.on('connection', function(socket) {
  var userId = makeId();
  users[userId] = {
    id: userId,
    sessionId: null,
    socket: socket
  };
  socket.emit('userId', userId);
  console.log('User ' + userId + ' connected.');

  socket.on('reboot', function(data, fn) {
    if (typeof data.sessionId !== 'string' || data.sessionId.length !== 16) {
      fn({ errorMessage: 'Invalid session ID.' });
      console.log('User ' + userId + ' attempted to reboot invalid session ' + String(data.sessionId) + '.');
      return;
    }

    if (typeof data.lastKnownTime !== 'number' || data.lastKnownTime % 1 !== 0 || data.lastKnownTime < 0) {
      fn({ errorMessage: 'Invalid lastKnownTime.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTime ' + String(data.lastKnownTime) + '.');
      return;
    }

    if (typeof data.lastKnownTimeUpdatedAt !== 'number' || data.lastKnownTimeUpdatedAt % 1 !== 0 || data.lastKnownTimeUpdatedAt < 0) {
      fn({ errorMessage: 'Invalid lastKnownTimeUpdatedAt.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid lastKnownTimeUpdatedAt ' + String(data.lastKnownTimeUpdatedAt) + '.');
      return;
    }

    if (typeof data.state !== 'string' || (data.state !== 'playing' && data.state !== 'paused')) {
      fn({ errorMessage: 'Invalid state.' });
      console.log('User ' + userId + ' attempted to reboot session ' + data.sessionId + ' with invalid state ' + String(data.state) + '.');
      return;
    }

    if (typeof data.videoId !== 'number' || data.videoId % 1 !== 0 || data.videoId < 0) {
      fn({ errorMessage: 'Invalid video ID.' });
      console.log('User ' + userId + ' attempted to reboot session with invalid video ' + String(data.videoId) + '.');
      return;
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
        state: data.state,
        videoId: data.videoId,
        userIds: [userId]
      };
      sessions[session.id] = session;
      users[userId].sessionId = data.sessionId;
      console.log('User ' + userId + ' rebooted session ' + users[userId].sessionId + ' with video ' + String(data.videoId) + ', time ' + String(data.lastKnownTime) + ', and state ' + data.state + ' for epoch ' + String(data.lastKnownTimeUpdatedAt) + '.');
    }

    fn({
      lastKnownTime: sessions[data.sessionId].lastKnownTime,
      lastKnownTimeUpdatedAt: sessions[data.sessionId].lastKnownTimeUpdatedAt.getTime(),
      state: sessions[data.sessionId].state
    });
  });

  socket.on('createSession', function(videoId, fn) {
    if (typeof videoId !== 'number' || videoId % 1 !== 0 || videoId < 0) {
      fn({ errorMessage: 'Invalid video ID.' });
      console.log('User ' + userId + ' attempted to create session with invalid video ' + String(videoId) + '.');
      return;
    }

    users[userId].sessionId = makeId();
    var now = new Date();
    var session = {
      id: users[userId].sessionId,
      lastKnownTime: 0,
      lastKnownTimeUpdatedAt: now,
      state: 'paused',
      userIds: [userId],
      videoId: videoId
    };
    sessions[session.id] = session;

    fn({
      lastKnownTime: sessions[users[userId].sessionId].lastKnownTime,
      lastKnownTimeUpdatedAt: sessions[users[userId].sessionId].lastKnownTimeUpdatedAt.getTime(),
      sessionId: users[userId].sessionId,
      state: sessions[users[userId].sessionId].state
    });
    console.log('User ' + userId + ' created session ' + users[userId].sessionId + ' with video ' + String(videoId) + '.');
  });

  socket.on('joinSession', function(sessionId, fn) {
    if (typeof sessionId !== 'string' || !sessions.hasOwnProperty(sessionId)) {
      fn({ errorMessage: 'Invalid session ID.' });
      console.log('User ' + userId + ' attempted to join nonexistent session ' + String(sessionId) + '.');
      return;
    }

    if (users[userId].sessionId !== null) {
      fn({ errorMessage: 'Already in a session.' });
      console.log('User ' + userId + ' attempted to join session ' + sessionId + ', but the user is already in session ' + users[userId].sessionId + '.');
      return;
    }

    users[userId].sessionId = sessionId;
    sessions[sessionId].userIds.push(userId);

    fn({
      videoId: sessions[sessionId].videoId,
      lastKnownTime: sessions[sessionId].lastKnownTime,
      lastKnownTimeUpdatedAt: sessions[sessionId].lastKnownTimeUpdatedAt.getTime(),
      state: sessions[sessionId].state
    });
    console.log('User ' + userId + ' joined session ' + sessionId + '.');
  });

  socket.on('leaveSession', function(_, fn) {
    if (users[userId].sessionId === null) {
      fn({ errorMessage: 'Not in a session.' });
      console.log('User ' + userId + ' attempted to leave a session, but the user was not in one.');
      return;
    }

    var sessionId = users[userId].sessionId;
    lodash.pull(sessions[sessionId].userIds, userId);
    users[userId].sessionId = null;

    fn(null);
    console.log('User ' + userId + ' left session ' + sessionId + '.');

    if (sessions[sessionId].userIds.length === 0) {
      delete sessions[sessionId];
      console.log('Session ' + sessionId + ' was deleted because there were no more users in it.');
    }
  });

  socket.on('updateSession', function(data, fn) {
    if (users[userId].sessionId === null) {
      fn({ errorMessage: 'Not in a session.' });
      console.log('User ' + userId + ' attempted to update a session, but the user was not in one.');
      return;
    }

    if (typeof data.lastKnownTime !== 'number' || data.lastKnownTime % 1 !== 0 || data.lastKnownTime < 0) {
      fn({ errorMessage: 'Invalid lastKnownTime.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTime ' + String(data.lastKnownTime) + '.');
      return;
    }

    if (typeof data.lastKnownTimeUpdatedAt !== 'number' || data.lastKnownTimeUpdatedAt % 1 !== 0 || data.lastKnownTimeUpdatedAt < 0) {
      fn({ errorMessage: 'Invalid lastKnownTimeUpdatedAt.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid lastKnownTimeUpdatedAt ' + String(data.lastKnownTimeUpdatedAt) + '.');
      return;
    }

    if (typeof data.state !== 'string' || (data.state !== 'playing' && data.state !== 'paused')) {
      fn({ errorMessage: 'Invalid state.' });
      console.log('User ' + userId + ' attempted to update session ' + users[userId].sessionId + ' with invalid state ' + String(data.state) + '.');
      return;
    }

    sessions[users[userId].sessionId].lastKnownTime = data.lastKnownTime;
    sessions[users[userId].sessionId].lastKnownTimeUpdatedAt = new Date(data.lastKnownTimeUpdatedAt);
    sessions[users[userId].sessionId].state = data.state;

    fn();
    console.log('User ' + userId + ' updated session ' + users[userId].sessionId + ' with time ' + String(data.lastKnownTime) + ' and state ' + data.state + ' for epoch ' + String(data.lastKnownTimeUpdatedAt) + '.');

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

  socket.on('ping', function(data, fn) {
    fn((new Date()).getTime());
    console.log('User ' + userId + ' pinged.');
  });

  socket.on('disconnect', function() {
    var sessionId = users[userId].sessionId;
    if (sessionId !== null) {
      lodash.pull(sessions[sessionId].userIds, userId);
      users[userId].sessionId = null;

      console.log('User ' + userId + ' left session ' + sessionId + '.');

      if (sessions[sessionId].userIds.length === 0) {
        delete sessions[sessionId];
        console.log('Session ' + sessionId + ' was deleted because there were no more users in it.');
      }
    }

    delete users[userId];
    console.log('User ' + userId + ' disconnected.');
  });
});

var server = http.listen(process.env.PORT || 3000, function() {
  console.log('Listening on port %d.', server.address().port);
});
