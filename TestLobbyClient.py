#!/usr/bin/env python
# coding=utf-8

import socket, inspect
import time
import threading
import traceback

from Crypto.Hash import MD5
from Crypto.Hash import SHA256

from base64 import b64decode as SAFE_DECODE_FUNC

UNICODE_ENCODING = "utf-8"
LEGACY_HASH_FUNC = MD5.new
SECURE_HASH_FUNC = SHA256.new

from base64 import b64encode as ENCODE_FUNC
from base64 import b64decode as DECODE_FUNC




NUM_CLIENTS = 1
NUM_UPDATES = 10000
USE_THREADS = False
CLIENT_NAME = "ubertest%02d"
CLIENT_PWRD = "KeepItSecretKeepItSafe%02d"
MAGIC_WORDS = "SqueamishOssifrage"

## number of keys to keep in memory
NUM_SESSION_KEYS = 4

HOST_SERVER = ("localhost", 8200)
MAIN_SERVER = ("lobby.springrts.com", 8200)
TEST_SERVER = ("lobby.springrts.com", 7000)
BACKUP_SERVERS = [
	("lobby1.springlobby.info", 8200),
	("lobby2.springlobby.info", 8200),
]

## commands that are allowed to be sent unencrypted
## (after session key is established, any subsequent
## SETSHAREDKEY commands will be encrypted entirely)
ALLOWED_OPEN_COMMANDS = ["GETPUBLICKEY", "GETSIGNEDMSG", "SETSHAREDKEY", "EXIT"]

class LobbyClient:
	def __init__(self, server_addr, username, password):
		self.host_socket = None
		self.socket_data = ""

		self.username = username
		self.password = password

		self.OpenSocket(server_addr)
		self.Init()

	def OpenSocket(self, server_addr):
		while (self.host_socket == None):
			## non-blocking so we do not have to wait on server
			self.host_socket = socket.create_connection(server_addr, 5)
			self.host_socket.setblocking(0)

	def Init(self):
		self.prv_ping_time = time.time()
		self.num_ping_msgs =     0
		self.max_ping_time =   0.0
		self.min_ping_time = 100.0
		self.sum_ping_time =   0.0
		self.iters = 0

		## time-stamps for encrypted data
		self.incoming_msg_ctr = 0
		self.outgoing_msg_ctr = 1

		self.data_send_queue = []

		self.server_info = ("", "", "", "")

		self.requested_registration   = False ## set on out_REGISTER
		self.requested_authentication = False ## set on out_LOGIN
		self.accepted_registration    = False ## set on in_REGISTRATIONACCEPTED
		self.rejected_registration    = False ## set on in_REGISTRATIONDENIED
		self.accepted_authentication  = False ## set on in_ACCEPTED

		## initialize key-exchange sequence (ends with ACKSHAREDKEY)
		## needed even if (for some reason) we do not want a secure
		## session to discover the server force_secure_{auths,comms}
		## settings

	def Send(self, data, batch = True):
		## test-client never tries to send unicode strings, so
		## we do not need to add encode(UNICODE_ENCODING) calls
		##
		## print("[Send][time=%d::iter=%d] data=\"%s\" sec_sess=%d key_acked=%d queue=%s batch=%d" % (time.time(), self.iters, data, self.use_secure_session(), self.client_acked_shared_key, self.data_send_queue, batch))
		assert(type(data) == str)

		def want_secure_command(data):
			cmd = data.split()
			cmd = cmd[0]
			return (self.want_secure_session and (not cmd in ALLOWED_OPEN_COMMANDS))

		def wrap_encrypt_sign_message(raw_msg):
			raw_msg = int32_to_str(self.outgoing_msg_ctr) + raw_msg
			enc_msg = encrypt_sign_message(self.aes_cipher_obj, raw_msg, self.use_msg_auth_codes())

			self.outgoing_msg_ctr += 1
			return enc_msg

		buf = data

		if (len(buf) == 0):
			return

		self.host_socket.send(buf)

	def Recv(self):
		num_received_bytes = len(self.socket_data)

		try:
			self.socket_data += self.host_socket.recv(4096)
		except:
			return

		if (len(self.socket_data) == num_received_bytes):
			return

		split_data = self.socket_data
		data_blobs = split_data[: len(split_data) - 1  ]
		final_blob = split_data[  len(split_data) - 1: ][0]

		def check_message_timestamp(msg):
			ctr = str_to_int32(msg)

			if (ctr <= self.incoming_msg_ctr):
				return False

			self.incoming_msg_ctr = ctr
			return True

		for raw_data_blob in data_blobs:
			if (len(raw_data_blob) == 0):
				continue

			## strips leading spaces and trailing carriage return
			self.Handle((raw_data_blob.rstrip('\r')).lstrip(' '))

		self.socket_data = final_blob

	def Handle(self, msg):
		## probably caused by trailing newline ("abc\n".split("\n") == ["abc", ""])
		if (len(msg) <= 1):
			return True

		assert(type(msg) == str)

		numspaces = msg.count(' ')

		if (numspaces > 0):
			command, args = msg.split(' ', 1)
		else:
			command = msg

		command = command.upper()

		funcname = 'in_%s' % command
		function = getattr(self, funcname)
		function_info = inspect.getargspec(function)
		total_args = len(function_info[0]) - 1
		optional_args = 0

		if (function_info[3]):
			optional_args = len(function_info[3])

		required_args = total_args - optional_args

		if (required_args == 0 and numspaces == 0):
			function()
			return True

		## bunch the last words together if there are too many of them
		if (numspaces > total_args - 1):
			arguments = args.split(' ', total_args - 1)
		else:
			arguments = args.split(' ')

		try:
			function(*(arguments))
			return True
		except Exception, e:
			print("Error handling: \"%s\" %s" % (msg, e))
			print(traceback.format_exc())
			return False


	def out_LOGIN(self):
		print("[LOGIN][time=%d::iter=%d] sec_sess=%d" % (time.time(), self.iters, self.use_secure_session()))

		if (self.use_secure_session()):
			self.Send("LOGIN %s %s" % (self.username, ENCODE_FUNC(self.password)))
		else:
			self.Send("LOGIN %s %s" % (self.username, ENCODE_FUNC(LEGACY_HASH_FUNC(self.password).digest())))

		self.requested_authentication = True

	def out_REGISTER(self):
		print("[REGISTER][time=%d::iter=%d] sec_sess=%d" % (time.time(), self.iters, self.use_secure_session()))

		if (self.use_secure_session()):
			self.Send("REGISTER %s %s" % (self.username, ENCODE_FUNC(self.password)))
		else:
			self.Send("REGISTER %s %s" % (self.username, ENCODE_FUNC(LEGACY_HASH_FUNC(self.password).digest())))

		self.requested_registration = True

	def out_CONFIRMAGREEMENT(self):
		print("[CONFIRMAGREEMENT][time=%d::iter=%d] sec_sess=%d" % (time.time(), self.iters, self.use_secure_session()))
		self.Send("CONFIRMAGREEMENT")


	def out_PING(self):
		print("[PING][time=%d::iters=%d]" % (time.time(), self.iters))

		self.Send("PING")

	def out_EXIT(self):
		self.host_socket.close()


	def out_SAYPRIVATE(self, user, msg):
		self.Send("SAYPRIVATE %s %s" % (user, msg))

	def in_TASSERVER(self, protocolVersion, springVersion, udpPort, serverMode):
		print("[TASSERVER][time=%d::iter=%d] proto=%s spring=%s udp=%s mode=%s" % (time.time(), self.iters, protocolVersion, springVersion, udpPort, serverMode))
		self.server_info = (protocolVersion, springVersion, udpPort, serverMode)

	def in_SERVERMSG(self, msg):
		print("[SERVERMSG][time=%d::iter=%d] %s" % (time.time(), self.iters, msg))


	def in_AGREEMENT(self, msg):
		pass

	def in_AGREEMENTEND(self):
		print("[AGREEMENDEND][time=%d::iter=%d]" % (time.time(), self.iters))
		assert(self.accepted_registration)
		assert(not self.accepted_authentication)

		self.out_CONFIRMAGREEMENT()
		self.out_LOGIN()


	def in_REGISTRATIONACCEPTED(self):
		print("[REGISTRATIONACCEPTED][time=%d::iter=%d]" % (time.time(), self.iters))

		## account did not exist and was created
		self.accepted_registration = True

		## trigger in_AGREEMENT{END}, second LOGIN there will trigger ACCEPTED
		self.out_LOGIN()

	def in_REGISTRATIONDENIED(self, msg):
		print("[REGISTRATIONDENIED][time=%d::iter=%d] %s" % (time.time(), self.iters, msg))

		self.rejected_registration = True


	def in_ACCEPTED(self, msg):
		print("[LOGINACCEPTED][time=%d::iter=%d]" % (time.time(), self.iters))

		## if we get here, everything checks out
		self.accepted_authentication = True

	def in_DENIED(self, msg):
		print("[DENIED][time=%d::iter=%d] %s" % (time.time(), self.iters, msg))

		## login denied, try to register first
		## nothing we can do if that also fails
		self.out_REGISTER()


	def in_MOTD(self, msg):
		pass
	def in_ADDUSER(self, msg):
		print(msg)
	def in_BATTLEOPENED(self, msg):
		print(msg)
	def in_UPDATEBATTLEINFO(self, msg):
		print(msg)
	def in_JOINEDBATTLE(self, msg):
		print(msg)
	def in_CLIENTSTATUS(self, msg):
		pass
	def in_LOGININFOEND(self):
		## do stuff here (e.g. "JOIN channel")
		pass

	def in_CHANNELTOPIC(self, msg):
		print(msg)
	def in_BATTLECLOSED(self, msg):
		print(msg)
	def in_REMOVEUSER(self, msg):
		print(msg)
	def in_LEFTBATTLE(self, msg):
		print(msg)

	def in_PONG(self):
		diff = time.time() - self.prv_ping_time

		self.min_ping_time = min(diff, self.min_ping_time)
		self.max_ping_time = max(diff, self.max_ping_time)
		self.sum_ping_time += diff
		self.num_ping_msgs += 1

		if (False and self.prv_ping_time != 0.0):
			print("[PONG] max=%0.3fs min=%0.3fs avg=%0.3fs" % (self.max_ping_time, self.min_ping_time, (self.sum_ping_time / self.num_ping_msgs)))

		self.prv_ping_time = time.time()

	def in_JOIN(self, msg):
		print(msg)
	def in_CLIENTS(self, msg):
		print(msg)
	def in_JOINED(self, msg):
		print(msg)
	def in_LEFT(self, msg):
		print(msg)

	def in_SAIDPRIVATE(self, msg):
		user, msg = msg.split(" ")
		self.out_SAYPRIVATE(user,"You said: " + msg)

	def in_SAYPRIVATE(self, msg):
		print "SAY " +  msg


	def Update(self):
		assert(self.host_socket != None)

		self.iters += 1

		if ((self.iters % 10) == 0):
			self.out_PING()

		threading._sleep(0.05)

		## eat through received data
		self.Recv()

	def Run(self, num_iters):
		while (self.iters < num_iters):
			self.Update()

		## say goodbye and close our socket
		self.out_EXIT()


def RunClients(num_clients, num_updates):
	clients = [None] * num_clients

	for i in xrange(num_clients):
		clients[i] = LobbyClient(HOST_SERVER, (CLIENT_NAME % i), (CLIENT_PWRD % i))

	for j in xrange(num_updates):
		for i in xrange(num_clients):
			clients[i].Update()

	for i in xrange(num_clients):
		clients[i].out_EXIT()


def RunClientThread(i, k):
	client = LobbyClient(HOST_SERVER, (CLIENT_NAME % i), (CLIENT_PWRD % i))

	print("[RunClientThread] running client %s" % client.username)
	client.Run(k)
	print("[RunClientThread] client %s finished" % client.username)

def RunClientThreads(num_clients, num_updates):
	threads = [None] * num_clients

	for i in xrange(num_clients):
		threads[i] = threading.Thread(target = RunClientThread, args = (i, num_updates, ))
		threads[i].start()
	for t in threads:
		t.join()


def main():
	if (not USE_THREADS):
		RunClients(NUM_CLIENTS, NUM_UPDATES)
	else:
		RunClientThreads(NUM_CLIENTS, NUM_UPDATES)

main()

